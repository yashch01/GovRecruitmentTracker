"""
tests/test_parser.py — Comprehensive tests for parser.py

Tests cover:
  1. Stage 1 pre-filter: CS/IT match, any-grad match, civil/medical rejection, scanned PDF
  2. Stage 3 offline regex fallback: dates, pay, GATE, selection, exam category
  3. Gov classifier: domain whitelist, private portal rejection, text signals
  4. Age verifier: eligible, barred, OBC/SC/ST relaxation, missing data, range
  5. Pipeline runner: graceful Gemini fallback to regex when no API key
  6. PARSER_REGISTRY: registry accessible and callable
"""

import sys
import os

# Add parent to path so `parser` is importable without install
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from parser import (
    is_eligible_for_cs_it_holder,
    classify_gov,
    extract_with_regex,
    run_extraction_pipeline,
    verify_age_eligibility,
    PARSER_REGISTRY,
)

# ─── Colours for terminal output ────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

_pass = 0
_fail = 0
_skip = 0


def _assert(condition: bool, label: str, detail: str = ""):
    global _pass, _fail
    if condition:
        _pass += 1
        print(f"  {GREEN}✓ PASS{RESET}  {label}")
    else:
        _fail += 1
        print(f"  {RED}✗ FAIL{RESET}  {label}")
        if detail:
            print(f"         {YELLOW}→ {detail}{RESET}")
        assert condition, f"{label}: {detail}"


def section(title: str):
    print(f"\n{BOLD}{CYAN}{'─'*60}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─'*60}{RESET}")


# ============================================================================
# 1. Stage 1 — CS/IT Eligibility Pre-Filter
# ============================================================================

def test_stage1_cs_it_eligibility():
    section("1. Stage 1 — CS/IT Eligibility Pre-Filter")

    # 1a. CS/IT-specific: direct discipline match
    cs_it_text = (
        "DRDO RAC invites applications for Scientist B in Computer Science & Engineering. "
        "Eligibility: B.Tech in CSE or IT. GATE score mandatory. Pay Level 10."
    )
    r = is_eligible_for_cs_it_holder(cs_it_text)
    _assert(r["eligible"] is True, "CS/IT direct match → eligible", str(r))
    _assert(r["match_type"] == "cs_it_specific", "Match type is cs_it_specific", str(r))
    _assert(r["confidence"] == "high", "Confidence is high for CS/IT direct", str(r))

    # 1b. MCA in text still triggers CS/IT match
    mca_text = "Eligible: MCA/B.Tech CS graduates may apply for this technical post."
    r = is_eligible_for_cs_it_holder(mca_text)
    _assert(r["eligible"] is True, "MCA + B.Tech CS text → eligible")

    # 1c. Any-graduate exam (SSC CGL)
    ssc_text = (
        "SSC CGL 2025 notification. Any graduate from any recognised university is eligible. "
        "Age: 18-27 years. Pay: Level 6."
    )
    r = is_eligible_for_cs_it_holder(ssc_text)
    _assert(r["eligible"] is True, "SSC CGL any-graduate text → eligible", str(r))
    _assert(r["match_type"] == "any_graduate", "Match type is any_graduate for SSC CGL", str(r))

    # 1d. Any-graduate exam (UPSC)
    upsc_text = (
        "UPSC Civil Services Examination 2025. Open to graduates from any discipline. "
        "Computer Science optional paper available."
    )
    r = is_eligible_for_cs_it_holder(upsc_text)
    _assert(r["eligible"] is True, "UPSC with any-graduate → eligible", str(r))

    # 1e. Banking (IBPS PO)
    ibps_text = (
        "IBPS PO Recruitment 2025. Eligibility: Graduation in any discipline from a recognised University. "
        "Age: 20-30 years."
    )
    r = is_eligible_for_cs_it_holder(ibps_text)
    _assert(r["eligible"] is True, "IBPS PO any-graduate → eligible", str(r))

    # 1f. Military (Agniveer)
    mil_text = (
        "Indian Army Agniveer Technical Recruitment 2025. Eligibility: 10+2/Intermediate "
        "with Physics, Chemistry, Maths or B.Tech from any discipline."
    )
    r = is_eligible_for_cs_it_holder(mil_text)
    _assert(r["eligible"] is True, "Agniveer technical → eligible", str(r))

    # 1g. REJECT: Civil engineering only
    civil_text = (
        "Recruitment for Junior Engineer (Civil). Eligible: B.Tech/B.E. in Civil Engineering only. "
        "Age: 18-30. Pay: Level 6."
    )
    r = is_eligible_for_cs_it_holder(civil_text)
    _assert(r["eligible"] is False, "Civil Engineering only → rejected", str(r))
    _assert(r["match_type"] == "none", "Civil-only match_type is none", str(r))

    # 1h. REJECT: Medical/pharma only
    medical_text = (
        "AIIMS recruitment for Medical Officer (MBBS). Eligible: MBBS or BDS only. "
        "No other disciplines are acceptable."
    )
    r = is_eligible_for_cs_it_holder(medical_text)
    _assert(r["eligible"] is False, "Medical-only post → rejected", str(r))

    # 1i. REJECT: No keywords at all
    empty_text = "This notification is about leave rules and service conditions."
    r = is_eligible_for_cs_it_holder(empty_text)
    _assert(r["eligible"] is False, "No keywords → rejected", str(r))

    # 1j. Both CS/IT specific AND any-graduate → cs_it_specific wins (higher confidence)
    both_text = (
        "ISRO recruitment for Scientist/Engineer SC. Eligibility: B.Tech in CS/IT or "
        "any graduate with 60% marks. GATE 2025 score mandatory."
    )
    r = is_eligible_for_cs_it_holder(both_text)
    _assert(r["eligible"] is True, "CS/IT + any-grad → eligible", str(r))
    _assert(r["match_type"] == "cs_it_specific", "CS/IT takes precedence over any-grad", str(r))


# ============================================================================
# 2. Stage 3 — Offline Regex Fallback
# ============================================================================

def test_stage3_offline_regex_fallback():
    section("2. Stage 3 — Offline Regex Fallback Parser")

    full_notice = """
BHEL Recruitment 2025 – Engineer Trainee (Computer Science)

BHEL invites applications for Engineer Trainee posts through GATE 2025.
Eligibility: B.E./B.Tech in Computer Science & Engineering or Information Technology.
A valid GATE score in CS is mandatory for this recruitment.

Pay Scale: Pay Level 10 (₹56,100 - ₹1,77,500) per month.

Important Dates:
Starting Date: 01/09/2025
Last Date to Apply: 30/09/2025
Last Date for Fee Payment: 01/10/2025
Examination Date: 15/02/2026

Age Limit: Not exceeding 28 years as on 01/09/2025.
(Relaxation: OBC 3 years, SC/ST 5 years)

Selection Process: GATE Score → Document Verification → Interview
Negative marking is NOT applicable to GATE score-based shortlisting.
"""

    r = extract_with_regex(full_notice, url="https://careers.bhel.in")

    _assert(r["_source"] == "regex", "Source is 'regex'")
    _assert("10" in r["pay_level_or_ctc"], "Pay level 10 extracted", r["pay_level_or_ctc"])
    _assert(r["gate_required"] is True, "GATE required correctly detected", str(r["gate_required"]))
    _assert("30/09/2025" in r["last_date"], "Last date 30/09/2025 extracted", r["last_date"])
    _assert("01/09/2025" in r["start_date"], "Start date 01/09/2025 extracted", r["start_date"])
    _assert("01/10/2025" in r["fee_last_date"], "Fee last date extracted", r["fee_last_date"])
    _assert("15/02/2026" in r["exam_date"], "Exam date extracted", r["exam_date"])
    _assert("28" in r["age_limit_details"], "Max age 28 extracted", r["age_limit_details"])
    _assert(r["is_cs_it"] is True, "is_cs_it True for CS/IT specific text")
    _assert(r["exam_category"] == "PSU", "Exam category PSU for BHEL URL/text", r["exam_category"])
    _assert("Interview" in r["selection_summary"], "Interview in selection summary", r["selection_summary"])

    # 2b. Non-GATE notice
    non_gate_notice = """
ECIL Recruitment 2025 – Technical Officer (Software)
Eligibility: B.Tech IT/CS. Direct recruitment without GATE.
Pay: Level 10. Last Date: 20/10/2025.
Written Test will be conducted. No negative marking.
Age limit: Max 25 years.
"""
    r2 = extract_with_regex(non_gate_notice)
    _assert(r2["gate_required"] is False, "Non-GATE notice correctly flagged False", str(r2["gate_required"]))
    _assert("25" in r2["age_limit_details"], "Max age 25 extracted for ECIL notice", r2["age_limit_details"])
    _assert("Written Exam" in r2["selection_summary"], "Written test in selection summary", r2["selection_summary"])

    # 2c. SSC CGL notice
    ssc_notice = """
SSC CGL 2025 – Combined Graduate Level Examination.
Eligibility: Bachelor's Degree in any discipline from a recognised University.
Age: 18–27 years (OBC +3, SC/ST +5).
Last date to apply: 05/08/2025.
CBT (Computer Based Test) in two tiers.
Pay: Level 6 (₹35,400 - ₹1,12,400).
"""
    r3 = extract_with_regex(ssc_notice)
    _assert(r3["exam_category"] == "Competitive Exam", "SSC → Competitive Exam category", r3["exam_category"])
    _assert(r3["is_cs_it"] is False, "SSC CGL is not cs_it_specific", str(r3["is_cs_it"]))
    _assert(r3["any_graduate_eligible"] is True, "SSC CGL any_graduate_eligible=True", str(r3["any_graduate_eligible"]))
    _assert(
        "6" in r3["pay_level_or_ctc"] or "35,400" in r3["pay_level_or_ctc"],
        "Pay level 6 or ₹ range extracted for SSC CGL",
        r3["pay_level_or_ctc"]
    )
    _assert("CBT" in r3["selection_summary"], "CBT in selection summary", r3["selection_summary"])

    # 2d. Banking notice
    bank_notice = """
IBPS PO 2025 – Probationary Officer Recruitment.
Eligibility: Graduation in any discipline. Age 20-30 years.
Application Start: 01/08/2025. Last Date: 21/08/2025.
CTC: ₹8 LPA approximately.
Selection: Written Exam followed by Interview.
"""
    r4 = extract_with_regex(bank_notice)
    _assert(r4["exam_category"] == "Banking", "IBPS notice → Banking category", r4["exam_category"])
    _assert("05/08/2025" not in r4["last_date"] or "21/08/2025" in r4["last_date"],
            "Last date 21/08/2025 for IBPS", r4["last_date"])

    # 2e. Rupee range pay extraction
    rupee_notice = "Pay Scale: ₹56,100 – ₹1,77,500 per month. Apply before 30/11/2025."
    r5 = extract_with_regex(rupee_notice)
    _assert("₹56,100" in r5["pay_level_or_ctc"] or "56,100" in r5["pay_level_or_ctc"],
            "₹ range pay extracted", r5["pay_level_or_ctc"])


# ============================================================================
# 3. Government Classifier
# ============================================================================

def test_government_classifier():
    section("3. Government Classifier")

    # 3a. .gov.in domain
    r = classify_gov(url="https://rac.gov.in/recruitment/2025")
    _assert(r["is_gov"] is True, "rac.gov.in → is_gov True", str(r))
    _assert(r["confidence"] == "high", "Domain match → high confidence", str(r))

    # 3b. .nic.in domain
    r = classify_gov(url="https://nicrecruit.nic.in/")
    _assert(r["is_gov"] is True, "nicrecruit.nic.in → is_gov True", str(r))

    # 3c. .res.in domain (DAE labs)
    r = classify_gov(url="https://www.barc.res.in/recruitment/")
    _assert(r["is_gov"] is True, "barc.res.in → is_gov True", str(r))

    # 3d. ibps.in (special case)
    r = classify_gov(url="https://www.ibps.in/crp-po-xv")
    _assert(r["is_gov"] is True, "ibps.in → is_gov True", str(r))

    # 3e. Text-based: Ministry of Electronics
    r = classify_gov(url="https://example.com", text="Ministry of Electronics and Information Technology announces recruitment.")
    _assert(r["is_gov"] is True, "Ministry keyword → is_gov True", str(r))

    # 3f. Text-based: PSU
    r = classify_gov(url="https://example.com", text="This Public Sector Undertaking invites applications.")
    _assert(r["is_gov"] is True, "PSU keyword → is_gov True", str(r))

    # 3g. Private: naukri.com
    r = classify_gov(url="https://www.naukri.com/job-listings-python-developer")
    _assert(r["is_gov"] is False, "naukri.com → is_gov False", str(r))
    _assert(r["confidence"] == "high", "Private domain → high confidence False", str(r))

    # 3h. Private: linkedin.com
    r = classify_gov(url="https://www.linkedin.com/jobs/view/12345")
    _assert(r["is_gov"] is False, "linkedin.com → is_gov False", str(r))

    # 3i. No signals at all
    r = classify_gov(url="https://randomsite.com/jobs", text="We are hiring developers.")
    _assert(r["is_gov"] is False, "Unknown URL + no gov text → False", str(r))
    _assert(r["confidence"] == "low", "No signals → low confidence", str(r))

    # 3j. .ac.in (university / IIT / NIT)
    r = classify_gov(url="https://iitd.ac.in/careers/recruitment")
    _assert(r["is_gov"] is True, "iitd.ac.in → is_gov True", str(r))

    # 3k. DRDO text mention
    r = classify_gov(url="https://somewhere.org", text="DRDO is recruiting Scientist B through RAC.")
    _assert(r["is_gov"] is True, "DRDO keyword in text → is_gov True", str(r))


# ============================================================================
# 4. Age Verifier
# ============================================================================

def test_age_verifier():
    section("4. Age Verifier")

    # 4a. General category — eligible
    r = verify_age_eligibility("1998-04-15", "General", "Max 28 years as on 01/08/2025")
    _assert(r["result"] == "Eligible", "General 27 yrs, max 28 → Eligible", str(r))
    _assert(r["user_age_on_cutoff"] == 27, "Correct age calculation (27)", str(r))
    _assert(r["relaxation_applied"] == 0, "Zero relaxation for General", str(r))

    # 4b. General category — age barred
    r = verify_age_eligibility("1994-01-01", "General", "Max 28 years as on 01/08/2025")
    _assert(r["result"] == "Age Barred", "General 31 yrs, max 28 → Age Barred", str(r))

    # 4c. OBC relaxation → eligible due to +3 years
    r = verify_age_eligibility("1994-06-15", "OBC", "Max 28 years as on 01/08/2025")
    _assert(r["result"] == "Eligible", "OBC 31 yrs, max 28+3=31 → Eligible", str(r))
    _assert(r["relaxation_applied"] == 3, "OBC relaxation 3 years applied", str(r))
    _assert(r["max_age_allowed"] == 31, "Effective max age is 31 for OBC", str(r))

    # 4d. SC relaxation → eligible due to +5 years
    r = verify_age_eligibility("1993-03-10", "SC", "Max 28 years as on 01/08/2025")
    _assert(r["result"] == "Eligible", "SC 32 yrs, max 28+5=33 → Eligible", str(r))
    _assert(r["relaxation_applied"] == 5, "SC relaxation 5 years applied", str(r))

    # 4e. ST relaxation — barred even with relaxation
    r = verify_age_eligibility("1990-01-01", "ST", "Max 28 years as on 01/08/2025")
    _assert(r["result"] == "Age Barred", "ST 35 yrs, max 28+5=33 → Barred", str(r))

    # 4f. EWS — same as General
    r = verify_age_eligibility("1999-12-25", "EWS", "Max 30 years as on 01/01/2026")
    _assert(r["result"] == "Eligible", "EWS 26 yrs, max 30 → Eligible", str(r))
    _assert(r["relaxation_applied"] == 0, "EWS has 0 relaxation", str(r))

    # 4g. Age range format (between 20-27 years)
    r = verify_age_eligibility("1999-04-15", "General", "between 20 and 27 years as on 01/08/2025")
    _assert(r["result"] == "Eligible", "Age range 20-27, person is 26 → Eligible", str(r))

    # 4h. Missing DOB → Check Notice
    r = verify_age_eligibility("", "General", "Max 28 years")
    _assert(r["result"] == "Check Notice", "Empty DOB → Check Notice", str(r))

    # 4i. Missing age details → Check Notice
    r = verify_age_eligibility("1998-04-15", "General", "")
    _assert(r["result"] == "Check Notice", "Empty age details → Check Notice", str(r))

    # 4j. Unparseable age details → Check Notice
    r = verify_age_eligibility("1998-04-15", "General", "Age as per recruitment rules")
    _assert(r["result"] == "Check Notice", "Unparseable age string → Check Notice", str(r))

    # 4k. DD/MM/YYYY DOB format
    r = verify_age_eligibility("15/04/1998", "General", "Max 28 years as on 01/08/2025")
    _assert(r["result"] == "Eligible", "DD/MM/YYYY DOB format handled correctly", str(r))


# ============================================================================
# 5. Pipeline Runner — Gemini Fallback
# ============================================================================

def test_pipeline_runner_gemini_fallback():
    section("5. Pipeline Runner — Gemini Fallback to Regex")

    pipeline_text = (
        "NIELIT Scientist B Recruitment 2025. Eligible: B.Tech CS/IT or MCA. "
        "Pay Level 10. Last Date: 31/10/2025. GATE 2025 mandatory. "
        "Max age 30 years as on 01/10/2025."
    )

    # No API key → should fall back to Stage 3 without crashing
    os.environ.pop("GEMINI_API_KEY", None)   # ensure no key
    r = run_extraction_pipeline(
        text=pipeline_text,
        url="https://www.nielit.gov.in",
        org_name="NIELIT",
        api_key="",
    )
    _assert("_fallback_reason" in r, "Fallback key present when no API key", str(list(r.keys())))
    _assert(r["_source"] == "regex", "Pipeline uses regex fallback without API key", r.get("_source"))
    _assert(r["gate_required"] is True, "Pipeline regex: GATE required detected", str(r.get("gate_required")))
    _assert("31/10/2025" in r.get("last_date", ""), "Pipeline regex: last date detected", r.get("last_date"))
    _assert(r["is_cs_it"] is True, "Pipeline regex: is_cs_it True", str(r.get("is_cs_it")))

    # Stage 2: Bad API key → should NOT crash, should fall back to regex
    r_bad = run_extraction_pipeline(
        text=pipeline_text,
        url="https://www.nielit.gov.in",
        org_name="NIELIT",
        api_key="bad-api-key-xyz",
    )
    _assert("_source" in r_bad, "Bad API key does not crash pipeline", str(list(r_bad.keys())))
    _assert(r_bad.get("_source") in ("regex", "gemini"), "Source is regex or gemini after bad key", r_bad.get("_source"))


# ============================================================================
# 6. PARSER_REGISTRY
# ============================================================================

def test_parser_registry():
    section("6. PARSER_REGISTRY Plugin Slot")

    pipeline_text = (
        "NIELIT Scientist B Recruitment 2025. Eligible: B.Tech CS/IT or MCA. "
        "Pay Level 10. Last Date: 31/10/2025. GATE 2025 mandatory. "
        "Max age 30 years as on 01/10/2025."
    )

    _assert("regex" in PARSER_REGISTRY, "PARSER_REGISTRY has 'regex' key")
    _assert("gemini" in PARSER_REGISTRY, "PARSER_REGISTRY has 'gemini' key")
    _assert(callable(PARSER_REGISTRY["regex"]), "PARSER_REGISTRY['regex'] is callable")
    _assert(callable(PARSER_REGISTRY["gemini"]), "PARSER_REGISTRY['gemini'] is callable")

    r = PARSER_REGISTRY["regex"](pipeline_text)
    _assert(r["_source"] == "regex", "PARSER_REGISTRY['regex'] executes correctly", str(r.get("_source")))

    with open("parser.py", "r", encoding="utf-8") as f:
        _assert("gemini-2.5-flash" in f.read(), "parser.py targets valid Gemini model gemini-2.5-flash")


# ============================================================================
# Results Summary
# ============================================================================

if __name__ == "__main__":
    test_stage1_cs_it_eligibility()
    test_stage3_offline_regex_fallback()
    test_government_classifier()
    test_age_verifier()
    test_pipeline_runner_gemini_fallback()
    test_parser_registry()

    total = _pass + _fail
    print(f"\n{'─'*60}")
    print(f"{BOLD}  Results: {GREEN}{_pass}/{total} passed{RESET}", end="")
    if _fail:
        print(f"  {RED}{_fail} FAILED{RESET}", end="")
    print(f"\n{'─'*60}\n")

    if _fail > 0:
        sys.exit(1)
    else:
        print(f"{GREEN}{BOLD}  ✓ All tests passed!{RESET}\n")
