import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from datetime import datetime
import calendar
from dotenv import load_dotenv

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

from backend.common.logger import setup_logging

logger = setup_logging("monthly-report")

# Load environment variables
load_dotenv()

SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")


def fetch_monthly_transactions() -> list:
    """
    Dummy function to fetch monthly transactions.
    In a real scenario, this would query QuestDB or your transaction database
    for trades executed in the current month.
    """
    # Mock data for demonstration
    now = datetime.now()
    return [
        {"date": f"{now.year}-{now.month:02d}-01", "symbol": "RELIANCE", "type": "BUY", "quantity": 10, "price": 2800.5, "total": 28005.0},
        {"date": f"{now.year}-{now.month:02d}-05", "symbol": "HDFCBANK", "type": "SELL", "quantity": 50, "price": 1600.0, "total": 80000.0},
        {"date": f"{now.year}-{now.month:02d}-12", "symbol": "INFY", "type": "BUY", "quantity": 25, "price": 1500.0, "total": 37500.0},
        {"date": f"{now.year}-{now.month:02d}-20", "symbol": "NIFTY", "type": "BUY", "quantity": 50, "price": 22000.0, "total": 1100000.0},
        {"date": f"{now.year}-{now.month:02d}-25", "symbol": "BTCUSDT", "type": "BUY", "quantity": 0.05, "price": 60000.0, "total": 3000.0},
    ]


def generate_pdf_report(transactions: list, filepath: str):
    """
    Generates a PDF report containing the transaction history.
    """
    doc = SimpleDocTemplate(filepath, pagesize=letter)
    elements = []
    
    styles = getSampleStyleSheet()
    title = Paragraph(f"Monthly Transaction Report - {datetime.now().strftime('%B %Y')}", styles['Title'])
    elements.append(title)
    elements.append(Spacer(1, 20))
    
    # Table header
    data = [["Date", "Symbol", "Type", "Quantity", "Price", "Total Value"]]
    
    # Table rows
    for t in transactions:
        data.append([
            t["date"], 
            t["symbol"], 
            t["type"], 
            str(t["quantity"]), 
            f"₹{t['price']:,.2f}" if "USDT" not in t["symbol"] else f"${t['price']:,.2f}",
            f"₹{t['total']:,.2f}" if "USDT" not in t["symbol"] else f"${t['total']:,.2f}"
        ])
    
    table = Table(data, hAlign='LEFT')
    
    # Add styling to table
    style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ])
    table.setStyle(style)
    
    elements.append(table)
    doc.build(elements)
    logger.info(f"Generated PDF report at {filepath}")


def send_email_with_pdf(pdf_filepath: str):
    """
    Sends an email with the generated PDF attached.
    """
    if not SENDER_EMAIL or not SENDER_PASSWORD or not RECEIVER_EMAIL:
        logger.error("Email credentials are not set in the .env file. Cannot send report.")
        return

    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECEIVER_EMAIL
    msg['Subject'] = f"Automated Trading System - Monthly Report [{datetime.now().strftime('%B %Y')}]"

    body = "Hello,\n\nPlease find attached the monthly transaction report for your Automated Trading System.\n\nBest regards,\nATS Bot"
    msg.attach(MIMEText(body, 'plain'))

    # Attach PDF
    try:
        with open(pdf_filepath, "rb") as f:
            attach = MIMEApplication(f.read(), _subtype="pdf")
            attach.add_header('Content-Disposition', 'attachment', filename=os.path.basename(pdf_filepath))
            msg.attach(attach)
    except Exception as e:
        logger.error(f"Failed to read PDF file for attachment: {e}")
        return

    # Send the email via SMTP (Using Gmail as default example)
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        text = msg.as_string()
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, text)
        server.quit()
        logger.info(f"Monthly report successfully sent to {RECEIVER_EMAIL}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")


def execute_monthly_report():
    """
    Main execution function to fetch data, generate PDF, and send the email.
    """
    logger.info("Starting monthly report generation...")
    
    transactions = fetch_monthly_transactions()
    
    if not transactions:
        logger.info("No transactions found for this month. Skipping report generation.")
        return
        
    pdf_filename = f"monthly_report_{datetime.now().strftime('%Y_%m')}.pdf"
    pdf_filepath = os.path.join(os.getcwd(), pdf_filename)
    
    generate_pdf_report(transactions, pdf_filepath)
    send_email_with_pdf(pdf_filepath)
    
    # Optionally delete the file after sending
    if os.path.exists(pdf_filepath):
        os.remove(pdf_filepath)
        logger.info(f"Cleaned up local file {pdf_filepath}")

if __name__ == "__main__":
    execute_monthly_report()
