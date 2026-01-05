import os
import sys
import csv
from django.db import transaction

# ------------------------------------------
# Django Setup
# ------------------------------------------
print("🔧 Setting up Django environment...")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
sys.path.insert(0, PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "genesis_engine.settings")

import django
django.setup()

print("✅ Django setup complete.")

from outbound.models import Lead  # adjust if app name differs


# ------------------------------------------
# CSV → Model Field Mapping
# ------------------------------------------
FIELD_MAP = {
    "First Name": "first_name",
    "Last Name": "last_name",
    "Title": "title",
    "Company Name": "company",
    "Email": "email",
    "Email Status": "email_status",
    "Seniority": "seniority",
    "Departments": "departments",
    "# Employees": "employees",
    "Industry": "industry",
    "Keywords": "keywords",
    "Person Linkedin Url": "person_linkedin",
    "Company Linkedin Url": "company_linkedin",
    "Website": "website",
    "Country": "country",
    "Technologies": "technologies",
}

print("📄 Field mapping loaded.")


# ------------------------------------------
# Import Function
# ------------------------------------------
def import_csv_leads(input_file, batch_size=500):

    print("\n🚀 Starting CSV import process...")
    print(f"📁 CSV Input File: {input_file}")

    leads_to_create = []
    total_rows = 0
    inserted = 0
    duplicates = 0
    errors = 0

    print("🔍 Opening CSV file...")

    with open(input_file, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        print("📌 CSV headers detected:", reader.fieldnames)

        for row in reader:
            total_rows += 1
            print(f"\n--- Processing row #{total_rows} ---")

            try:
                email = (row.get("Email") or "").strip().lower()

                # ---------------------------
                # Duplicate Check
                # ---------------------------
                if email:
                    print(f"🔎 Checking for duplicate email: {email}")
                    if Lead.objects.filter(email=email).exists():
                        duplicates += 1
                        print("⚠️ Duplicate found → Skipping this row.")
                        continue
                else:
                    print("⚠️ No email found → Skipping row.")
                    errors += 1
                    continue

                # ---------------------------
                # Field Mapping
                # ---------------------------
                lead_data = {}
                print("🗺️ Mapping CSV fields into model fields...")
                for csv_col, model_field in FIELD_MAP.items():
                    value = row.get(csv_col, "").strip()
                    print(f"   {csv_col} → {model_field} = {value}")
                    lead_data[model_field] = value or None

                # ---------------------------
                # Parse Employees (int)
                # ---------------------------
                emp = (row.get("# Employees") or "").strip()
                print(f"👥 Raw employees value: {emp}")

                if emp.isdigit():
                    lead_data["employees"] = int(emp)
                    print(f"   ➝ Parsed employees: {lead_data['employees']}")
                else:
                    lead_data["employees"] = None
                    print("   ➝ Invalid employees value → Set to None")

                # ---------------------------
                # Always default score
                # ---------------------------
                lead_data["score"] = False
                print("📌 score=False assigned.")

                # ---------------------------
                # Create model instance
                # ---------------------------
                print("📦 Creating Lead instance (not saved yet)...")
                leads_to_create.append(Lead(**lead_data))

                # ---------------------------
                # Batch insert
                # ---------------------------
                if len(leads_to_create) >= batch_size:
                    print(f"📤 Inserting batch of {len(leads_to_create)} leads into DB...")
                    Lead.objects.bulk_create(leads_to_create)
                    inserted += len(leads_to_create)
                    leads_to_create = []
                    print("✅ Batch insert complete.")

            except Exception as e:
                errors += 1
                print(f"❌ ERROR processing row #{total_rows}: {e}")
                continue

        # Final leftover batch
        if leads_to_create:
            print(f"\n📤 Inserting final batch of {len(leads_to_create)} leads...")
            Lead.objects.bulk_create(leads_to_create)
            inserted += len(leads_to_create)
            print("✅ Final batch insert complete.")

    # ------------------------------------------
    # Summary Report
    # ------------------------------------------
    print("\n🎉 CSV IMPORT SUMMARY")
    print("-----------------------------")
    print(f"📌 Total Rows Read: {total_rows}")
    print(f"📥 Successfully Inserted: {inserted}")
    print(f"♻️ Duplicates Skipped: {duplicates}")
    print(f"⚠️ Errors / Bad Rows: {errors}")
    print("-----------------------------")
    print("🚀 Import process finished.\n")


# ------------------------------------------
# Run Import
# ------------------------------------------
if __name__ == "__main__":

    input_file = os.path.join(
        PROJECT_ROOT,
        "csv-json/apollo-contacts-saas-dimeji.csv"
    )

    import_csv_leads(input_file)
