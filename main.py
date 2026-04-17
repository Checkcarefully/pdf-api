from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import fitz
import pdfplumber
import io
from typing import List
from pypdf import PdfWriter, PdfReader

app = FastAPI()

# CORS 支持
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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

    return {"tables_count": len(all_tables), "tables": all_tables}


@app.post("/merge")
async def merge_pdfs(files: List[UploadFile] = File(..., description="上传多个PDF文件")):
    """合并多个 PDF（支持任意数量）"""
    if len(files) < 2:
        return {"error": "至少需要上传2个PDF文件"}

    writer = PdfWriter()
    total_pages = 0

    for file in files:
        contents = await file.read()
        reader = PdfReader(io.BytesIO(contents))
        for page in reader.pages:
            writer.add_page(page)
            total_pages += 1

    output = io.BytesIO()
    writer.write(output)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=merged.pdf"}
    )


@app.get("/")
async def root():
    return {
        "service": "PDF API",
        "endpoints": ["/extract/text", "/extract/tables", "/merge"],
        "docs": "/docs"
    }
