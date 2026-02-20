import sys
sys.path.append("/home/priyanshu/Documents/CL/closewire/backend")
import main
import pprint

program = {
    "program_name": "Test Product",
    "value_proposition": "A great car",
    "key_features": ["4 wheels", "steering wheel"],
    "target_audience": "anyone",
    "positioning_angle": "cheap",
    "duration": "N/A",
    "format": "N/A",
    "weekly_time_commitment": "N/A",
    "program_fee_inr": "500000",
    "placement_support_details": "N/A",
    "certification_details": "N/A",
    "curriculum_modules": [],
    "learning_outcomes": [],
    "cohort_start_dates": [],
    "faqs": [],
    "projects_use_cases": [],
    "program_curriculum_coverage": "N/A",
    "tools_frameworks_technologies": [],
    "emi_or_financing_options": "Yes"
}

persona = main._generate_persona(program, forced_archetype_id="car_buyer")
print("===== PERSONA =====")
pprint.pprint(persona)

state = {
    "round": 1,
    "max_rounds": 10,
    "messages": [
        {"agent": "student", "content": "Tell me about this car's mileage."}
    ],
    "history_for_reporting": [],
    "counsellor_position": {},
    "student_position": {},
    "student_inner_state": {},
    "program": program,
    "persona": persona,
    "deal_status": "in_progress",
    "negotiation_metrics": {},
    "retry_context": {}
}

print("\n===== COUNSELLOR PROMPT =====")
print(main._build_counsellor_prompt(state))

print("\n===== STUDENT PROMPT =====")
print(main._build_student_prompt(state))
