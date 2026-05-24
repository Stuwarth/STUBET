from PyPDF2 import PdfReader
import sys

reader = PdfReader('Analysis_Real Madrid_vs_Real Oviedo.pdf')
print(f"Total pages: {len(reader.pages)}")

# Write to UTF-8 file
with open('pdf_madrid_oviedo.txt', 'w', encoding='utf-8') as f:
    for i, page in enumerate(reader.pages):
        text = page.extract_text()
        f.write(f"\n{'='*60}\n")
        f.write(f"=== PAGE {i+1} ===\n")
        f.write(f"{'='*60}\n")
        if text:
            f.write(text + "\n")
        else:
            f.write("[NO TEXT EXTRACTED]\n")

print("Done - written to pdf_madrid_oviedo.txt")
