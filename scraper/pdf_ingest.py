"""
PDF ingestion -- pulls text AND tables out of a datasheet PDF.

Why tables matter: industrial datasheets almost always put specs in a table
(Attribute | Value | Unit columns), and plain text extraction often mangles
table layout into garbage. pdfplumber gives us tables as structured rows,
which we then flatten into clean text so the SAME extractor.llm_extractor
module can process it -- no separate "PDF extraction logic" needed.
"""

import pdfplumber
from dataclasses import dataclass


@dataclass
class ParsedPDF:
    source_id: str
    clean_text: str
    page_count: int


def pdf_to_clean_text(pdf_path: str) -> ParsedPDF:
    text_chunks = []

    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            page_text = page.extract_text() or ""
            if page_text.strip():
                text_chunks.append(f"[Page {i+1}]\n{page_text.strip()}")

            # Tables often hold the actual spec data -- extract separately and
            # flatten into "Column: Value" style lines so the LLM can read them cleanly
            tables = page.extract_tables()
            for t_idx, table in enumerate(tables):
                if not table or len(table) < 2:
                    continue
                header = [h.strip() if h else "" for h in table[0]]
                for row in table[1:]:
                    row_text = ", ".join(
                        f"{header[i]}: {cell}" for i, cell in enumerate(row)
                        if cell and i < len(header) and header[i]
                    )
                    if row_text:
                        text_chunks.append(f"[Page {i+1}, Table {t_idx+1}] {row_text}")

        page_count = len(pdf.pages)

    return ParsedPDF(
        source_id=pdf_path,
        clean_text="\n\n".join(text_chunks),
        page_count=page_count,
    )


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python pdf_ingest.py path/to/datasheet.pdf")
    else:
        result = pdf_to_clean_text(sys.argv[1])
        print(f"Pages: {result.page_count}")
        print(f"Extracted {len(result.clean_text)} characters\n")
        print(result.clean_text[:1000])
