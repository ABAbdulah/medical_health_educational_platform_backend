"""AI Study Planner: builds a day-by-day plan from profile preferences."""

from datetime import date, timedelta

SUBJECT_WEIGHTS = {
    "Medicine": 0.25,
    "Surgery": 0.15,
    "Paediatrics": 0.15,
    "OBGYN": 0.15,
    "Psychiatry": 0.10,
    "Ethics": 0.10,
    "Emergency": 0.10,
}

SUBJECT_TOPICS = {
    "Medicine": [
        "Atrial fibrillation", "Acute coronary syndrome", "Heart failure", "COPD", "Asthma",
        "Type 2 diabetes", "Hypothyroidism", "Hyperthyroidism", "CKD", "UTI", "Pneumonia",
        "Pulmonary embolism", "DVT", "Stroke", "TIA", "Sepsis", "Meningitis", "Endocarditis",
        "Anaemia workup", "Liver function interpretation",
    ],
    "Surgery": [
        "Appendicitis", "Bowel obstruction", "AAA", "Renal colic", "Urinary retention",
        "Cholecystitis", "Pancreatitis", "Hernias", "Breast lumps", "Thyroid nodules",
        "Post-op complications", "Trauma primary survey",
    ],
    "Paediatrics": [
        "Febrile child", "Kawasaki disease", "Intussusception", "Croup", "Bronchiolitis",
        "Paediatric asthma", "Gastroenteritis and dehydration", "Neonatal jaundice",
        "Developmental milestones", "Immunisation schedule", "Child protection",
    ],
    "OBGYN": [
        "Pre-eclampsia", "Gestational diabetes", "Ectopic pregnancy", "PPH",
        "Shoulder dystocia", "PID", "Antepartum haemorrhage", "Miscarriage",
        "Contraception counselling", "Cervical screening", "Menopause",
    ],
    "Psychiatry": [
        "Schizophrenia", "Bipolar disorder", "Major depression", "Suicide risk assessment",
        "Anxiety disorders", "Substance use disorders", "Delirium vs dementia", "Eating disorders",
    ],
    "Ethics": [
        "Capacity and consent", "Notifiable diseases", "Confidentiality", "Mandatory reporting",
        "Open disclosure", "End-of-life decisions", "Cultural safety",
    ],
    "Emergency": [
        "Anaphylaxis", "Chest pain approach", "Dyspnoea approach", "Headache approach",
        "Abdominal pain approach", "Altered consciousness", "Seizure first presentation",
        "Overdose management", "STEMI management",
    ],
}

REVISION_INTERVALS = [3, 7, 14, 30]  # spaced repetition offsets in days


def compute_weights(strong: list[str], weak: list[str]) -> dict[str, float]:
    weights = dict(SUBJECT_WEIGHTS)
    for s in strong:
        if s in weights:
            weights[s] *= 0.7
    for s in weak:
        if s in weights:
            weights[s] *= 1.5
    total = sum(weights.values())
    return {k: v / total for k, v in weights.items()}


def generate_plan_tasks(
    exam_date: date,
    daily_hours: float,
    working_status: str | None,
    strong_subjects: list[str],
    weak_subjects: list[str],
    start: date | None = None,
) -> list[dict]:
    """Returns list of dicts: {due_date, subject, topic, estimated_hours, task_type}."""
    start = start or date.today()
    # leave the final week before the exam for pure revision
    study_end = max(start + timedelta(days=1), exam_date - timedelta(days=7))
    total_days = max((study_end - start).days, 1)

    if working_status == "full_time":
        daily_hours = min(daily_hours, 4.0)

    weights = compute_weights(strong_subjects, weak_subjects)
    # build a weighted round-robin of (subject, topic) pairs sized to the study window
    pool: list[tuple[str, str]] = []
    for subject, weight in weights.items():
        n_topics = max(1, round(weight * total_days))
        topics = SUBJECT_TOPICS[subject]
        for i in range(n_topics):
            pool.append((subject, topics[i % len(topics)]))
    pool = pool[:total_days]

    tasks: list[dict] = []
    for offset, (subject, topic) in enumerate(pool):
        day = start + timedelta(days=offset)
        study_hours = round(daily_hours * 0.6, 1)
        tasks.append({
            "due_date": day, "subject": subject, "topic": topic,
            "estimated_hours": study_hours, "task_type": "study",
        })
        tasks.append({
            "due_date": day, "subject": subject, "topic": f"MCQ practice: {topic}",
            "estimated_hours": round(daily_hours * 0.4, 1), "task_type": "mcq_practice",
        })
        # spaced repetition revision passes
        for interval in REVISION_INTERVALS:
            rev_day = day + timedelta(days=interval)
            if rev_day < exam_date:
                tasks.append({
                    "due_date": rev_day, "subject": subject, "topic": f"Revise: {topic}",
                    "estimated_hours": 0.5, "task_type": "revision",
                })

    # mock exam every 3rd week
    mock_day = start + timedelta(days=20)
    while mock_day < exam_date:
        tasks.append({
            "due_date": mock_day, "subject": "Mixed", "topic": "Full mock exam (150 MCQs)",
            "estimated_hours": 3.5, "task_type": "mock_exam",
        })
        mock_day += timedelta(days=21)

    # final-week intensive revision
    day = study_end
    while day < exam_date:
        tasks.append({
            "due_date": day, "subject": "Mixed", "topic": "Final revision: weak topics + flagged MCQs",
            "estimated_hours": daily_hours, "task_type": "revision",
        })
        day += timedelta(days=1)

    tasks.sort(key=lambda t: t["due_date"])
    return tasks
