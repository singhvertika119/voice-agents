KB = """Sunrise Clinic, Sector 62 Noida. Timings: Mon-Sat 9am-7pm, Sunday closed.
Doctors: Dr. Sharma (cardiologist, Mon/Wed/Sat), Dr. Gupta (pediatrician, Tue/Thu/Fri).
Fees: consultation Rs 600, follow-up within 7 days Rs 300, ECG Rs 400.
Appointments: book by phone or at the front desk. Cancellation free up to 4 hours before.
Reports are ready in 24 hours; collect at the desk or ask for a WhatsApp link."""

# (question, substrings; any one must appear in a correct answer)
QUESTIONS = [
    ("clinic kab khulta hai?", ["9", "nau"]),
    ("Sunday ko clinic open hai kya?", ["closed", "band", "nahi", "no"]),
    ("consultation ki fees kitni hai", ["600", "chhe sau", "six hundred"]),
    ("follow up ka kitna lagega", ["300", "teen sau", "three hundred"]),
    ("ECG ke kitne paise", ["400", "chaar sau", "four hundred"]),
    ("cardiologist kaun hai", ["sharma"]),
    ("bachon ke doctor kab baithte hain", ["tue", "thu", "fri", "mangal", "guru", "shukra"]),
    ("Dr Gupta Monday ko aate hain?", ["nahi", "no", "not", "tue"]),
    ("appointment cancel karna hai, paise lagenge?", ["free", "nahi", "muft", "4"]),
    ("meri report kab milegi", ["24", "chaubees", "twenty"]),
    ("report WhatsApp pe mil sakti hai?", ["whatsapp", "haan", "yes"]),
    ("clinic kahan hai", ["sector 62", "noida"]),
    ("Do you have a dermatologist?", ["nahi", "not", "no", "don't", "nahin"]),
    ("what are your timings on Saturday", ["9", "7"]),
    ("kya aap MRI karte ho", ["nahi", "not", "no", "don't", "nahin"]),
]
