from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from docx import Document
ROOT=Path(__file__).resolve().parents[1]/'samples'
def save_docx(path,lines):
    doc=Document()
    for line in lines:doc.add_paragraph(line)
    doc.save(path)
def save_pdf(path,lines):
    c=canvas.Canvas(str(path),pagesize=A4);c.setFont('Helvetica',11);y=795
    for line in lines:
        c.drawString(45,y,line);y-=20
    c.save()
if __name__=='__main__':
    (ROOT/'resumes').mkdir(parents=True,exist_ok=True);(ROOT/'job-descriptions').mkdir(exist_ok=True)
    experienced=['SYNTHETIC DEMONSTRATION RESUME','Alex Morgan','alex@example.test','Cloud Engineer','Skills','Python, Amazon Web Services, Docker, Terraform, Linux','Work Experience','Cloud Engineer at Example Systems','Jan 2020 - Dec 2023','Platform Engineer at Demo Labs','Jan 2024 - Dec 2025','Education','BEng, Example University, 2019']
    graduate=['SYNTHETIC DEMONSTRATION RESUME','Sam Rivera','sam@example.test','Software Engineer','Skills','Python, Java, Git, SQL','Projects','Built a small inventory application with Python and SQL.','Education','BSc, Example College, 2026','No professional employment yet.']
    career=['SYNTHETIC DEMONSTRATION RESUME','Taylor Chen','taylor@example.test','Data Analyst','Skills','Python, SQL, Pandas, NumPy','Work Experience','Operations Associate at Sample Logistics','Jan 2021 - Dec 2023','Data Analyst at Example Analytics','Jun 2023 - Dec 2025','Education','BSc, Example University, 2020']
    save_pdf(ROOT/'resumes/experienced-cloud.pdf',experienced)
    save_docx(ROOT/'resumes/graduate-software.docx',graduate)
    save_docx(ROOT/'resumes/career-change-data.docx',career)
    save_docx(ROOT/'job-descriptions/cloud-engineer.docx',['SYNTHETIC DEMONSTRATION JOB DESCRIPTION','Cloud Engineer','Required skills: Python, Amazon Web Services, Docker, Terraform, Linux.','Acceptable titles: Cloud Engineer, Platform Engineer.','Minimum professional experience: 3 years.','Do not score personal identity, age, gender, or other protected characteristics.'])
    (ROOT/'README.md').write_text('All names, employers and resumes are fictional. example.test addresses cannot receive invitations. Replace contact details in the review screen with a verified test inbox you control before sending. These three documents are excluded from model training. Capture real AWS extraction outputs; no fabricated model response is bundled.\n')
    print('Created 3 synthetic resumes and a sample JD.')
