from pathlib import Path
import re, subprocess, sys

root = Path(__file__).resolve().parent
app_file = root / 'app.py'
if not app_file.exists():
    print('ERROR: Put this installer and pdf_reports.py in the same folder as app.py.')
    raise SystemExit(1)
source = app_file.read_text(encoding='utf-8')
marker = 'register_pdf_routes(app, get_db, login_required)'
if marker not in source:
    anchor = "if __name__ == \"__main__\":"
    if anchor not in source:
        print('ERROR: Could not find the Flask app startup section. No files were changed.')
        raise SystemExit(1)
    insertion = "\nfrom pdf_reports import register_pdf_routes\nregister_pdf_routes(app, get_db, login_required)\n\n"
    backup = app_file.with_suffix('.py.before_pdf_backup')
    if not backup.exists():
        backup.write_text(source, encoding='utf-8')
    source = source.replace(anchor, insertion + anchor, 1)
    app_file.write_text(source, encoding='utf-8')

requirements = root / 'requirements.txt'
if requirements.exists():
    req = requirements.read_text(encoding='utf-8')
    if 'reportlab' not in req.lower():
        requirements.write_text(req.rstrip() + '\nreportlab>=4.2,<5\n', encoding='utf-8')
else:
    requirements.write_text('Flask>=3.0,<4.0\nFlask-WTF>=1.2,<2.0\nreportlab>=4.2,<5\n', encoding='utf-8')

print('Installing PDF dependency into the currently active Python environment...')
result = subprocess.run([sys.executable, '-m', 'pip', 'install', 'reportlab>=4.2,<5'])
if result.returncode:
    print('Dependency installation failed. Your app.py backup is available as app.py.before_pdf_backup.')
    raise SystemExit(result.returncode)
print('\nPDF report route added. Restart the app and open Reports. A Download PDF button must be added to reports.html as described in README.txt.')
