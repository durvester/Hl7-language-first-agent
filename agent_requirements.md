# Dr. Walter Reed Cardiology Clinic - A2A Agent Functional Requirements

## 1. Agent Overview
**Agent Name:** Dr. Walter Reed Cardiology Referral Agent  
**Primary Function:** Manage and process cardiology referrals for Dr. Walter Reed's clinic  
**Clinic Location:** Walter Reed Clinic, Manhattan  

## 2. Core Functional Requirements

### 2.1 Provider Verification
**Requirement:** Validate that referrals come from authorized healthcare providers
- **Input Required:** Provider's first name, last name, NPI (optional but preferred)
- **Verification Method:** NPPES API (https://npiregistry.cms.hhs.gov/api-page)
- **Success Criteria:** Provider must be found in NPPES database with active status
- **Failure Action:** Reject referral if provider cannot be verified

### 2.2 Insurance Verification  
**Requirement:** Ensure patient has acceptable insurance coverage
- **Accepted Payers:** 
  - United Healthcare
  - Aetna
  - Cigna
  - Blue Cross Blue Shield (BCBS)
  - Kaiser
- **Success Criteria:** Patient must have active coverage with one of the accepted payers
- **Failure Action:** Reject referral if insurance is not accepted

### 2.3 Clinical Referral Validation
**Requirement:** Verify referral meets Dr. Reed's consultation criteria

#### 2.3.1 Required Patient Identifiers
- Full name
- Date of birth (DOB)
- Medical record number (MRN)

#### 2.3.2 Acceptable Referral Reasons (at least one required)
- Chest pain / suspected ischemia (ICD-10: R07.89, I20.x, I25.x)
- Abnormal stress test or imaging (CPT: 93015, 93350, 78452 with abnormal result)
- Documented arrhythmia (ICD-10: I48.x, I49.x)
- Heart failure / cardiomyopathy (ICD-10: I50.x, I42.x)
- Valvular heart disease (ICD-10: I34.x, I35.x, I36.x, I37.x)
- Syncope / presyncope (ICD-10: R55) with suspected cardiac etiology
- Resistant hypertension (ICD-10: I10; uncontrolled on ≥3 antihypertensives)
- Congenital heart disease follow-up (ICD-10: Q2x.x)
- Suspected pulmonary hypertension (ICD-10: I27.x)

#### 2.3.3 Required Documentation
- **ECG** (CPT: 93000) – tracing and interpretation
- **Recent Echocardiogram** (CPT: 93306) – report if performed
- **Relevant Labs** – troponins, BNP/NT-proBNP, electrolytes, renal function
- **Medication List** – current medications, especially antihypertensives, antiarrhythmics, anticoagulants
- **Primary Care Summary** – vitals, risk factors, initial therapy attempts

#### 2.3.4 Automatic Deferrals
Referrals will be automatically deferred if:
- Indication does not match acceptable criteria
- Required diagnostic documentation is missing
- Request is for preventive care only without complications

### 2.4 Appointment Scheduling
**Requirement:** Schedule appointments for validated referrals

#### 2.4.1 Schedule Parameters
- **Days:** Mondays and Thursdays only
- **Hours:** 11:00 AM - 3:00 PM
- **Patient Type:** New patients only
- **Location:** Walter Reed Clinic, Manhattan

#### 2.4.2 Scheduling Logic
- Check Dr. Reed's calendar for available slots
- Schedule first available appointment within acceptable timeframe
- Update calendar with new appointment

### 2.5 Communication and Documentation
**Requirement:** Provide appropriate responses to referral requests
- **Approval:** Send confirmation with appointment details
- **Denial:** Send denial notice with specific reasons
- **Deferral:** Send deferral notice with missing requirements

## 3. Success Criteria
- All referrals are processed within defined business rules
- Valid referrals result in scheduled appointments
- Invalid referrals receive clear rejection/deferral explanations
- Dr. Reed's calendar remains accurate and up-to-date
- All communications are professional and compliant

## 4. Business Rules Summary
1. **SCOPE RESTRICTION:** ONLY new patient cardiology referrals - zero tolerance for off-topic requests
2. **Conversational First:** Always attempt negotiation and clarifying questions before deferring
3. **Emergency Override:** Immediately direct critical/acute cases to urgent care/ED
4. **No exceptions** to insurance requirements (United, Aetna, Cigna, BCBS, Kaiser only)
5. **No exceptions** to provider verification (must be active in NPPES)
6. **No exceptions** to scheduling availability (Mon/Thu 11 AM-3 PM, 1-hour slots)
7. **Defer Only When:** User definitively states information unavailable OR information clearly doesn't qualify after negotiation
8. **Professional Communication:** All responses must be professional, compliant, and focused
9. **No Medical Advice:** Never provide medical advice, treatment recommendations, or interpret results
10. **Documentation Required:** All approvals must include complete appointment package with intake form