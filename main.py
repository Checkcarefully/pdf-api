from fastapi import FastAPI, UploadFile, File
import fitz
import pdfplumber
import io

app = FastAPI()


@app.post("/extract/text")
async def extract_text(file: UploadFile = File(...)):
    contents = await file.read()
    doc = fitz.open(stream=contents, filetype="pdf")

    text = ""
    for page in doc:
        text += page.get_text()

    return {"text": text, "pages": len(doc)}


@app.post("/extract/tables")
async def extract_tables(file: UploadFile = File(...)):
    """使用 pdfplumber 提取表格"""
    contents = await file.read()

    all_tables = []

    with pdfplumber.open(io.BytesIO(contents)) as pdf:
        for page_num, page in enumerate(pdf.pages):
            tables = page.extract_tables()

            for table in tables:
                if table and len(table) > 0:
                    all_tables.append({
                        "page": page_num + 1,
                        "rows": len(table),
                        "columns": len(table[0]) if table[0] else 0,
                        "data": table
                    })

    return {
        "tables_count": len(all_tables),
        "tables": all_tables
    }


@app.get("/")
async def root():
    return {"message": "PDF API Service", "endpoints": ["/extract/text", "/extract/tables"]}
