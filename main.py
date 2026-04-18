from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import fitz
import pdfplumber
import io
import re
from typing import List
from pypdf import PdfWriter, PdfReader

app = FastAPI()

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


@app.post("/extract/invoice")
async def extract_invoice(file: UploadFile = File(...)):
    contents = await file.read()
    doc = fitz.open(stream=contents, filetype="pdf")
    full_text = ""
    for page in doc:
        full_text += page.get_text()

    result = {}
    if "增值税专用发票" in full_text:
        result["invoice_type"] = "增值税专用发票"
    elif "增值税普通发票" in full_text:
        result["invoice_type"] = "增值税普通发票"
    else:
        result["invoice_type"] = "未知"

    import re
    code_match = re.search(r'发票代码[：:]\s*(\d{10,12})', full_text)
    result["invoice_code"] = code_match.group(1) if code_match else ""

    number_match = re.search(r'发票号码[：:]\s*(\d{8,20})', full_text)
    result["invoice_number"] = number_match.group(1) if number_match else ""

    date_match = re.search(r'(\d{4}年\d{1,2}月\d{1,2}日)', full_text)
    result["date"] = date_match.group(1) if date_match else ""

    amount_match = re.search(r'[¥￥]\s*(\d+\.?\d{0,2})', full_text)
    result["amount"] = amount_match.group(1) if amount_match else ""

    seller_match = re.search(r'销售方.*?\n.*?([\u4e00-\u9fa5]{4,})', full_text, re.DOTALL)
    result["seller_name"] = seller_match.group(1) if seller_match else ""

    buyer_match = re.search(r'购买方.*?\n.*?([\u4e00-\u9fa5]{4,})', full_text, re.DOTALL)
    result["buyer_name"] = buyer_match.group(1) if buyer_match else ""

    tax_id_matches = re.findall(r'[A-Z0-9]{15,20}', full_text)
    if len(tax_id_matches) >= 2:
        result["seller_tax_id"] = tax_id_matches[0]
        result["buyer_tax_id"] = tax_id_matches[1]
    else:
        result["seller_tax_id"] = tax_id_matches[0] if tax_id_matches else ""
        result["buyer_tax_id"] = ""

    return result


@app.post("/merge")
async def merge_pdfs(files: List[UploadFile] = File(..., description="上传多个PDF文件")):
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
        "endpoints": ["/extract/text", "/extract/tables", "/extract/invoice", "/merge"],
        "docs": "/docs"
    }
