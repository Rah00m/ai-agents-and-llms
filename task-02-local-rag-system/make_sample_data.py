"""Creates two small demo knowledge bases in ./data (a fictional company handbook PDF and a sales workbook).

    python make_sample_data.py
"""
import os
import random
from datetime import date, timedelta

from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

HANDBOOK = {
    "1. Leave Policy": [
        "Every full-time employee receives 21 days of paid annual leave per calendar year. Leave accrues monthly, and new joiners receive a pro-rated amount.",
        "Employees may carry over a maximum of 5 unused annual leave days into the next year. Any days above this limit expire on 31 March.",
        "Sick leave is separate from annual leave and is granted for up to 10 days per year. A medical certificate is required for absences longer than 2 consecutive days.",
        "Parental leave is 16 weeks for the primary caregiver and 4 weeks for the secondary caregiver, paid at full salary.",
    ],
    "2. Remote Work": [
        "Employees may work remotely up to 2 days per week with their manager's agreement. Teams agree on their in-office days at the start of each quarter.",
        "During remote days everyone must be reachable during the core hours of 10:00 to 15:00 Cairo time. Meetings are not scheduled outside these hours without consent.",
        "Working from another country for more than 14 days in a year needs written approval from the People team because of tax and insurance rules.",
    ],
    "3. Expenses and Travel": [
        "Meals during business travel are reimbursed up to 25 USD per day. Alcohol is not reimbursable under any circumstances.",
        "Expense claims must be submitted with receipts within 30 days of the purchase. Late claims are rejected unless the Finance team grants an exception.",
        "Any single expense above 500 USD requires prior approval from a department director. Flights must be booked at least 14 days in advance in economy class.",
    ],
    "4. IT and Security": [
        "Passwords must be changed every 90 days and must not be reused. Multi-factor authentication is mandatory for email, the VPN and the finance system.",
        "Lost or stolen laptops must be reported to the IT helpdesk within 2 hours. The device will be wiped remotely.",
        "Employees must not install unapproved software. Requests for new tools are submitted through the IT portal and reviewed within 5 working days.",
    ],
    "5. Onboarding and Benefits": [
        "New employees receive their laptop and accounts on their first day. Each joiner is paired with a buddy and follows a 30-60-90 day plan agreed with their manager.",
        "Health insurance starts after the 3-month probation period and covers the employee and up to 3 dependants.",
        "Every employee has a yearly learning budget of 1,200 USD for courses, books and conferences. Unused budget does not carry over.",
    ],
}


def make_pdf(path):
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(path, pagesize=A4, title="Nile Tech Employee Handbook")
    story = [Paragraph("Nile Tech Employee Handbook", styles["Title"]), Spacer(1, 12),
             Paragraph("This handbook describes the main policies that apply to all employees of Nile Tech (a fictional company used for this demo).", styles["BodyText"]), Spacer(1, 12)]
    for i, (title, paras) in enumerate(HANDBOOK.items(), start=1):
        story.append(Paragraph(title, styles["Heading2"]))
        for p in paras:
            story += [Paragraph(p, styles["BodyText"]), Spacer(1, 6)]
        if i in (2, 4):
            story.append(PageBreak())
    doc.build(story)


def make_xlsx(path):
    rnd = random.Random(7)
    wb = Workbook()
    ws = wb.active
    ws.title = "Sales"
    ws.append(["Date", "Region", "Salesperson", "Product", "Units", "Unit Price", "Revenue"])
    people = {"North": ["Amira", "Omar"], "South": ["Karim", "Laila"], "East": ["Youssef", "Nour"], "West": ["Hana", "Tarek"]}
    prices = {"Router": 120, "Switch": 340, "Firewall": 980, "Access Point": 210}
    day = date(2026, 7, 1)
    for _ in range(40):
        region = rnd.choice(list(people))
        product = rnd.choice(list(prices))
        units = rnd.randint(1, 20)
        ws.append([day, region, rnd.choice(people[region]), product, units, prices[product], units * prices[product]])
        day += timedelta(days=rnd.randint(1, 3))
    t = wb.create_sheet("Targets")
    t.append(["Region", "Q3 Revenue Target"])
    for region, target in (("North", 30000), ("South", 25000), ("East", 28000), ("West", 22000)):
        t.append([region, target])
    wb.save(path)


if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    make_pdf("data/handbook.pdf")
    make_xlsx("data/sales.xlsx")
    print("Created data/handbook.pdf and data/sales.xlsx")
