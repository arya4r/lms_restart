"""Where each loan master column is shown. Every column of the uploaded loan master is kept
on the loan as it came in (Loan.details); these lists only decide which group it appears in.
Columns in none of the groups show under "Other loan master fields"."""

LOAN_KEYS = [
    "NBFCLAN", "ApplicationId", "LoanAccountNumber", "ProductName", "LoanAmount", "TotalPrinciple",
    "IRR", "Tenure", "EMIAmount", "LoanDisbursalDate", "FirstRepaymentDate", "LastRepaymentDate",
    "TotalInterest", "TotalEMis", "NetDisbursementAmount", "ProcFees", "StampDuty", "Insurance",
    "DocCharges", "BPI", "BPIDays", "SmartFinCharges", "CreditShield", "RSA", "AdvanceEMI",
    "Subvention", "LoanStatus", "system", "UTR",
]

LEAD_KEYS = [
    "SourcingChannel", "ApprovalMethod", "LeadId", "LeadCreatedDate", "LeadStatus",
    "DisbursementStatus", "ApprovedDate", "DealerName", "DealerCity", "DealerState", "OEM", "Model",
    "Variant", "SchemeName", "RequestedLoanAmount", "ApprovedLoanAmount", "BureauScore", "LTV",
    "OnRoadPrice", "ExshowroomPrice", "AccessoriesCharges", "MarginMoney", "EvfinScore", "IsSTP",
    "LenderName", "SanctionAmount", "XIRR", "AnnualPercentangeRate",
]

COAPPLICANT_KEYS = [
    "CoApplicantName", "RelationWithCustomer", "CoApplicantDOB", "CoApplicantPANNo",
    "CoApplicantUIDMasked", "CoApplicantGender", "CoApplicantMaritalStatus", "CoApplicantMobile",
    "CoApplicantEmailId", "CoApplicantIncomeProof", "CoApplicantCurrentAddress", "CoApplicantCity",
    "CoApplicantPincode", "CoApplicantState", "CoApplicantResidentType", "CoApplicantBureauScore",
]

CLIENT_KEYS = [
    "ClientId", "ClientName", "LeadMobileNumber", "ClientCreatedDate", "ClientType", "PAN", "Gender",
    "DOB", "Age", "MaritalStatus", "EmploymentStatus", "Occupation", "MonthlyIncome", "ResidentType",
    "AddressType", "Remarks", "SOName", "SOEmpId", "CurrentAddress", "CurrentDistrict",
    "CurrentPincode", "CurrentState", "CurrentResidentType", "PermanentAddress", "PermanentCity",
    "PermanentPincode", "PermanentState", "PermanentResidentType", "OrganizationName",
    "CustomerEmailId", "AadharNumber", "OpsMaker", "OpsMakerId",
]

BANK_KEYS = [
    "BeneficiaryAccountDetail", "BankAccountNo", "BankAccountHolderName", "BankBranchName", "BankName",
    "IFSC", "AccountType", "UMRN", "BankShare", "NBFCShare", "BankEMI", "BankTenure",
    "ProcessingFeeUTR", "StampDutyUTR", "InsuranceUTR",
]

LOAN_GROUPS = [("Loan", LOAN_KEYS), ("Lead details", LEAD_KEYS), ("Co-applicant", COAPPLICANT_KEYS)]
CLIENT_GROUPS = [("Client", CLIENT_KEYS), ("Bank account", BANK_KEYS)]


PLACEHOLDERS = {"", "-", "na", "n/a", "null", "not there", "nil", "0000-00-00"}


def _shown(v) -> bool:
    return v is not None and str(v).strip().lower() not in PLACEHOLDERS


def group(details: dict, groups) -> dict:
    """{group name: {column: value}} for the non-blank values, in the group order."""
    out, used = {}, set()
    for name, keys in groups:
        vals = {k: details[k] for k in keys if k in details and _shown(details[k])}
        used.update(keys)
        if vals:
            out[name] = vals
    return out


# columns that are not shown anywhere on the loan page
HIDDEN_KEYS = {"RepaymentType"}


def loan_groups(details: dict) -> dict:
    out = group(details, LOAN_GROUPS)
    # client and bank columns live on the client tab, so they are not repeated here
    used = {k for _, keys in LOAN_GROUPS + CLIENT_GROUPS for k in keys} | HIDDEN_KEYS
    other = {k: v for k, v in details.items() if k not in used and _shown(v)}
    if other:
        out["Other loan master fields"] = other
    return out


def client_groups(details: dict) -> dict:
    return group(details, CLIENT_GROUPS)
