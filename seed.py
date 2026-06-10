"""Seed script for AMC Compass AI.

Idempotent: collections are only inserted when their table is empty, and
users are looked up by email before creation. Safe to re-run.

Usage:  python seed.py
"""

import asyncio
import logging
import random
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session_factory
from models import (
    AdminUser, AIConversation, AIMessage, BurnoutResource, Flashcard,
    FlashcardProgress, GuidelineTopic, MotivationQuote, Note, NoteFolder,
    Question, QuestionAttempt, QuestionOption, RecallAnalytics, RecallDocument,
    RecallTopic, StudyPlan, StudyTask, User, UserPreferences,
)
from seed_data.articles import ARTICLES
from seed_data.mcqs_1 import MCQS_1
from seed_data.mcqs_2 import MCQS_2
from seed_data.mcqs_3 import MCQS_3
from seed_data.quotes import QUOTES
from seed_data.topics_part1 import TOPICS_1
from seed_data.topics_part2 import TOPICS_2
from services.planner_service import generate_plan_tasks
from utils.security import hash_password

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("seed")

rng = random.Random(42)  # deterministic seed data


async def _table_empty(db: AsyncSession, model) -> bool:
    count = (await db.execute(select(func.count()).select_from(model))).scalar_one()
    return count == 0


async def seed_quotes(db: AsyncSession) -> None:
    if not await _table_empty(db, MotivationQuote):
        log.info("quotes: already seeded, skipping")
        return
    db.add_all(MotivationQuote(**q) for q in QUOTES)
    await db.commit()
    log.info("quotes: inserted %d", len(QUOTES))


async def seed_articles(db: AsyncSession) -> None:
    if not await _table_empty(db, BurnoutResource):
        log.info("articles: already seeded, skipping")
        return
    db.add_all(BurnoutResource(**a) for a in ARTICLES)
    await db.commit()
    log.info("articles: inserted %d", len(ARTICLES))


async def seed_topics(db: AsyncSession) -> None:
    if not await _table_empty(db, GuidelineTopic):
        log.info("topics: already seeded, skipping")
        return
    topics = TOPICS_1 + TOPICS_2
    db.add_all(GuidelineTopic(**t) for t in topics)
    await db.commit()
    log.info("topics: inserted %d", len(topics))


async def seed_questions(db: AsyncSession) -> None:
    if not await _table_empty(db, Question):
        log.info("questions: already seeded, skipping")
        return
    mcqs = MCQS_1 + MCQS_2 + MCQS_3
    for i, mcq in enumerate(mcqs, start=1):
        question = Question(
            qid=10000 + i,
            subject=mcq["subject"],
            topic=mcq["topic"],
            difficulty=mcq["difficulty"],
            question_text=mcq["question_text"],
            explanation=mcq["explanation"],
            learning_point=mcq["learning_point"],
            reference_source=mcq["reference"],
            status="published",
            options=[QuestionOption(**opt) for opt in mcq["options"]],
        )
        db.add(question)
    await db.commit()
    log.info("questions: inserted %d", len(mcqs))


async def _get_or_create_user(db: AsyncSession, email: str, password: str, **fields) -> tuple[User, bool]:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is not None:
        return user, False
    user = User(email=email, password_hash=hash_password(password), **fields)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user, True


async def seed_admin(db: AsyncSession) -> None:
    admin, created = await _get_or_create_user(
        db, "admin@amccompass.com", "Admin123!",
        full_name="AMC Compass Admin", country="Australia",
        graduation_year=2010, working_status="full_time",
        subscription_status="annual",
    )
    if created:
        db.add(AdminUser(user_id=admin.id, role="superadmin", permissions=["*"]))
        # admins skip the candidate onboarding wizard
        db.add(UserPreferences(user_id=admin.id, onboarding_complete=True))
        await db.commit()
        log.info("admin user: created (admin@amccompass.com / Admin123!)")
    else:
        log.info("admin user: already exists, skipping")


async def seed_demo_user(db: AsyncSession) -> None:
    demo, created = await _get_or_create_user(
        db, "demo@amccompass.com", "Demo123!",
        full_name="Demo Candidate", country="India",
        graduation_year=2019, working_status="part_time", amc_attempts=1,
    )
    if not created:
        log.info("demo user: already exists, skipping demo content")
        return

    today = date.today()
    exam_date = today + timedelta(days=180)

    # --- preferences (onboarding already complete for the demo account) ---
    db.add(UserPreferences(
        user_id=demo.id, exam_date=exam_date, daily_hours=4.0,
        strong_subjects=["Medicine"], weak_subjects=["OBGYN", "Psychiatry"],
        learning_style="mixed", onboarding_complete=True,
    ))

    # --- 6-month study plan via the real planner service ---
    plan = StudyPlan(user_id=demo.id, target_exam_date=exam_date, status="active")
    db.add(plan)
    await db.flush()
    tasks = generate_plan_tasks(
        exam_date=exam_date, daily_hours=4.0, working_status="part_time",
        strong_subjects=["Medicine"], weak_subjects=["OBGYN", "Psychiatry"],
        start=today - timedelta(days=14),  # plan started 2 weeks ago so today has tasks
    )
    completed_count = 0
    for t in tasks:
        is_past = t["due_date"] < today
        completed = is_past and rng.random() < 0.8
        completed_count += completed
        db.add(StudyTask(
            plan_id=plan.id, subject=t["subject"], topic=t["topic"],
            task_type=t["task_type"], estimated_hours=t["estimated_hours"],
            due_date=t["due_date"], completed=completed,
            completed_at=datetime.combine(t["due_date"], datetime.min.time(), tzinfo=timezone.utc)
            if completed else None,
        ))
    plan.completion_pct = round(100 * completed_count / max(len(tasks), 1), 1)

    # --- MCQ attempt history (past 14 days incl. today) for accuracy/readiness ---
    questions = (await db.execute(
        select(Question.id).order_by(Question.id).limit(60)
    )).scalars().all()
    now = datetime.now(timezone.utc)
    for i, qid in enumerate(questions):
        days_ago = 13 - (i * 14 // max(len(questions), 1))
        attempted_at = now - timedelta(days=days_ago, minutes=rng.randint(0, 600))
        correct = rng.random() < 0.68
        db.add(QuestionAttempt(
            user_id=demo.id, question_id=qid,
            selected_letter=rng.choice("ABCDE"), is_correct=correct,
            time_taken_seconds=rng.randint(35, 180), attempted_at=attempted_at,
        ))

    # --- 15 flashcards with staggered SM-2 progress ---
    flashcard_data = [
        ("First-line treatment for eclamptic seizure?", "Magnesium sulfate 4 g IV load, then 1 g/hr infusion. Not benzodiazepines.", "OBGYN"),
        ("Diagnostic BP threshold for pre-eclampsia?", ">=140/90 after 20 weeks on two occasions, plus one feature of organ dysfunction.", "OBGYN"),
        ("GDM screening test and timing?", "75 g OGTT at 24-28 weeks (earlier if risk factors).", "OBGYN"),
        ("ECG hallmark of WPW?", "Short PR interval (<120 ms) with delta wave and broad QRS.", "Medicine"),
        ("AF >48h: cardiovert immediately?", "No - anticoagulate 3 weeks (or TOE first) unless haemodynamically unstable.", "Medicine"),
        ("Most common cause of infective endocarditis in IVDU?", "Staphylococcus aureus, typically affecting the tricuspid valve.", "Medicine"),
        ("Empirical antibiotics for adult bacterial meningitis?", "IV ceftriaxone 2 g + dexamethasone; add benzylpenicillin if Listeria risk.", "Medicine"),
        ("Kawasaki disease diagnostic criteria?", "Fever >=5 days plus 4 of 5: conjunctivitis, oral changes, rash, cervical node >1.5 cm, extremity changes.", "Paediatrics"),
        ("Croup first-line treatment?", "Oral corticosteroid (dexamethasone 0.15 mg/kg); nebulised adrenaline if severe.", "Paediatrics"),
        ("Target age group for intussusception?", "3 months - 2 years; classic triad: colicky pain, vomiting, redcurrant jelly stool.", "Paediatrics"),
        ("First-line agent for acute psychosis with agitation?", "Oral antipsychotic (e.g. olanzapine) +/- benzodiazepine; IM if oral refused.", "Psychiatry"),
        ("Key components of suicide risk assessment?", "Ideation, plan, means, intent, protective factors, past attempts, mental state.", "Psychiatry"),
        ("Anaphylaxis first-line drug, dose, route?", "Adrenaline 0.5 mg (500 mcg) IM into lateral thigh, repeat every 5 min as needed.", "Emergency"),
        ("Criteria for capacity to consent?", "Understand, retain, weigh information, and communicate the decision.", "Ethics"),
        ("Sepsis: first-hour bundle?", "Blood cultures, lactate, broad-spectrum IV antibiotics, 30 mL/kg crystalloid if hypotensive.", "Emergency"),
    ]
    for i, (front, back, subject) in enumerate(flashcard_data):
        card = Flashcard(
            user_id=demo.id, front_text=front, back_text=back,
            source_type=rng.choice(["mcq", "topic", "manual"]), subject=subject,
        )
        db.add(card)
        await db.flush()
        reps = i % 3
        db.add(FlashcardProgress(
            flashcard_id=card.id, user_id=demo.id,
            ease_factor=2.5, interval_days=[0, 1, 3][reps], repetitions=reps,
            next_review_date=today + timedelta(days=[0, 0, 2][reps] - (1 if i % 5 == 0 else 0)),
            last_reviewed=now - timedelta(days=2) if reps else None,
        ))

    # --- notes ---
    folder = NoteFolder(user_id=demo.id, name="Cardiology")
    db.add(folder)
    await db.flush()
    db.add_all([
        Note(
            user_id=demo.id, title="Atrial fibrillation - rate vs rhythm",
            folder_id=folder.id, tags=["cardiology", "high-yield"],
            subject="Medicine", topic="Atrial fibrillation",
            content="<h2>AF management</h2><p>Stable AF &gt;48h or unknown duration: <strong>rate control</strong> "
                    "(beta-blocker) + anticoagulation per CHA2DS2-VA. Cardioversion only after 3 weeks of "
                    "anticoagulation or TOE exclusion of thrombus.</p><ul><li>Unstable: synchronised DC cardioversion</li>"
                    "<li>Assess stroke risk in ALL patients</li></ul>",
        ),
        Note(
            user_id=demo.id, title="Pre-eclampsia essentials",
            tags=["obgyn", "exam"],
            subject="OBGYN", topic="Pre-eclampsia",
            content="<h2>Pre-eclampsia</h2><p>New HTN &ge;20 weeks + organ dysfunction (proteinuria no longer "
                    "mandatory).</p><p><strong>AMC Pearl:</strong> eclampsia treatment = MgSO4, not diazepam. "
                    "Definitive management is delivery.</p>",
        ),
        Note(
            user_id=demo.id, title="Paeds fever red flags",
            tags=["paediatrics"],
            subject="Paediatrics", topic="Febrile child",
            content="<h2>Febrile child</h2><p>Red flags: age &lt;3 months with fever &ge;38, lethargy, poor perfusion, "
                    "petechial rash, bulging fontanelle. Any febrile neonate needs full septic workup.</p>",
        ),
    ])

    # --- AI tutor conversation history ---
    convo = AIConversation(user_id=demo.id, title="Management of GDM", topic_tag="OBGYN")
    db.add(convo)
    await db.flush()
    db.add_all([
        AIMessage(conversation_id=convo.id, role="user", content="How is gestational diabetes managed in Australia?"),
        AIMessage(
            conversation_id=convo.id, role="assistant",
            content="Management of gestational diabetes follows a stepwise approach:\n\n"
                    "**1. Lifestyle first-line (RANZCOG):** medical nutrition therapy, 30 minutes of moderate exercise "
                    "most days, and blood glucose self-monitoring (fasting + 1-2h postprandial).\n\n"
                    "**2. Pharmacotherapy second-line:** insulin is the preferred agent when targets are not met within "
                    "1-2 weeks. Metformin is an accepted alternative after discussion of risks/benefits.\n\n"
                    "AMC Pearl: [targets are fasting <=5.0-5.5 mmol/L and 2-hour postprandial <=6.7 mmol/L - "
                    "exact cutoffs vary by service, learn your reference values]\n\n"
                    "Source: [RANZCOG - Gestational Diabetes Mellitus; SA Health Perinatal Practice Guidelines]",
            sources=[{"name": "RANZCOG"}, {"name": "SA Health"}],
        ),
        AIMessage(conversation_id=convo.id, role="user", content="What are the glucose targets on the 75g OGTT for diagnosis?"),
    ])

    await db.commit()
    log.info("demo user: created with plan (%d tasks), attempts, 15 flashcards, 3 notes, conversation",
             len(tasks))


async def seed_recalls(db: AsyncSession) -> None:
    """Synthetic recall analytics so the dashboard heatmap and recalls page render with data."""
    if not await _table_empty(db, RecallDocument):
        log.info("recalls: already seeded, skipping")
        return

    today = date.today()
    months = []
    y, m = today.year, today.month
    for _ in range(6):  # last 6 months, oldest first
        months.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    months.reverse()

    recall_topics = [
        # (topic, subtopic, subject, base frequency)
        ("Pre-eclampsia", "Magnesium sulfate", "OBGYN", 9),
        ("Gestational diabetes", "OGTT interpretation", "OBGYN", 7),
        ("Ectopic pregnancy", "Beta-hCG monitoring", "OBGYN", 5),
        ("Postpartum haemorrhage", "Uterotonics", "OBGYN", 6),
        ("Atrial fibrillation", "Anticoagulation", "Medicine", 8),
        ("Acute coronary syndrome", "STEMI criteria", "Medicine", 7),
        ("Heart failure", "HFrEF management", "Medicine", 5),
        ("Sepsis", "First-hour bundle", "Medicine", 6),
        ("Pulmonary embolism", "Wells score", "Medicine", 5),
        ("Febrile child", "Septic workup thresholds", "Paediatrics", 8),
        ("Croup", "Dexamethasone dosing", "Paediatrics", 5),
        ("Bronchiolitis", "Supportive care", "Paediatrics", 4),
        ("Intussusception", "Air enema", "Paediatrics", 4),
        ("Suicide risk assessment", "Means restriction", "Psychiatry", 7),
        ("Schizophrenia", "First-episode psychosis", "Psychiatry", 5),
        ("Major depression", "Stepped care", "Psychiatry", 4),
        ("Capacity and consent", "Refusal of treatment", "Ethics", 6),
        ("Child protection", "Mandatory reporting", "Ethics", 5),
        ("Anaphylaxis", "IM adrenaline", "Emergency", 8),
        ("Overdose management", "Paracetamol nomogram", "Emergency", 5),
        ("Appendicitis", "Pregnancy considerations", "Surgery", 5),
        ("Bowel obstruction", "Drip and suck", "Surgery", 4),
    ]

    for mi, month in enumerate(months):
        doc = RecallDocument(
            filename=f"recalls-{month}.pdf", exam_month=month,
            file_path=f"uploads/recalls/recalls-{month}.pdf", status="approved",
        )
        db.add(doc)
        await db.flush()
        for topic, subtopic, subject, base in recall_topics:
            freq = max(0, base + rng.randint(-3, 3) - (len(months) - 1 - mi))
            if freq == 0:
                continue
            rt = RecallTopic(
                document_id=doc.id, topic=topic, subtopic=subtopic,
                subject=subject, frequency=freq,
            )
            db.add(rt)
            await db.flush()
            trend = "up" if mi >= len(months) - 2 and freq > base else ("down" if freq < base - 1 else "stable")
            db.add(RecallAnalytics(topic_id=rt.id, month=month, frequency=freq, trend_direction=trend))

    await db.commit()
    log.info("recalls: inserted %d documents across %s..%s", len(months), months[0], months[-1])


async def main() -> None:
    async with async_session_factory() as db:
        await seed_quotes(db)
        await seed_articles(db)
        await seed_topics(db)
        await seed_questions(db)
        await seed_admin(db)
        await seed_recalls(db)
        await seed_demo_user(db)  # after questions + recalls (uses question ids)
    log.info("Seed complete.")


if __name__ == "__main__":
    asyncio.run(main())
