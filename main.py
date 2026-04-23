from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import fitz
import pdfplumber
import io
import re
from typing import List
from pypdf import PdfWriter, PdfReader

# 常量配置
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

app = FastAPI(
    title="PDF工具箱",
    description="""
    ## 快速开始

    ### 场景1：PDF转文本
    ```bash
    curl -X POST "https://pdf-api-production-0ea0.up.railway.app/extract/text" \\
         -F "file=@试卷.pdf"
    ```

    ### 场景2：PDF合并
    ```bash
    curl -X POST "https://pdf-api-production-0ea0.up.railway.app/merge" \\
         -F "files=@1班.pdf" -F "files=@2班.pdf"
    ```

    ### 场景3：提取表格
    ```bash
    curl -X POST "https://pdf-api-production-0ea0.up.railway.app/extract/tables" \\
         -F "file=@成绩表.pdf"
    ```

    ### 场景4：PDF拆分
    ```bash
    curl -X POST "https://pdf-api-production-0ea0.up.railway.app/split" \\
         -F "file=@证书.pdf" \\
         -F "pages=1-10"
    ```
    """,
    version="1.0.0"
)

# Add at the top of main.py, after imports
request_count = 0

@app.middleware("http")
async def count_requests(request, call_next):
    global request_count
    request_count += 1
    print(f"Total requests: {request_count}")
    response = await call_next(request)
    return response

# Add this endpoint to check stats
@app.get("/stats")
async def stats():
    return {"total_requests": request_count, "message": "Visit count updated"}

# 挂载静态文件目录（前端页面）
app.mount("/static", StaticFiles(directory="static"), name="static")

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def validate_pdf(file: UploadFile) -> bytes:
    """校验文件类型和大小"""
    # 校验格式
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(400, detail=f"只接受PDF文件，收到：{file.filename}")

    # 读取内容
    contents = file.file.read()

    # 校验大小
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(400, detail=f"文件超过50MB限制（{len(contents) // 1024 // 1024}MB）")

    # 校验PDF魔数
    if not contents.startswith(b'%PDF'):
        raise HTTPException(400, detail="文件不是有效的PDF格式")

    return contents


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """全局异常处理"""
    return JSONResponse(
        status_code=500,
        content={"error": "处理失败，请检查PDF是否加密、损坏或格式异常", "detail": str(exc)}
    )


@app.post("/extract/text")
async def extract_text(file: UploadFile = File(...)):
    """PDF转文本"""
    contents = validate_pdf(file)

    try:
        doc = fitz.open(stream=contents, filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text()
        return {"text": text, "pages": len(doc), "filename": file.filename}
    except Exception as e:
        raise HTTPException(400, detail=f"PDF解析失败：{str(e)}")


@app.post("/extract/tables")
async def extract_tables(file: UploadFile = File(...)):
    """提取PDF表格"""
    contents = validate_pdf(file)

    try:
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
        return {"tables_count": len(all_tables), "tables": all_tables, "filename": file.filename}
    except Exception as e:
        raise HTTPException(400, detail=f"表格提取失败：{str(e)}")


@app.post("/extract/invoice")
async def extract_invoice(file: UploadFile = File(...)):
    """发票信息提取"""
    contents = validate_pdf(file)

    try:
        doc = fitz.open(stream=contents, filetype="pdf")
        full_text = ""
        for page in doc:
            full_text += page.get_text()

        result = {"filename": file.filename}

        if "增值税专用发票" in full_text:
            result["invoice_type"] = "增值税专用发票"
        elif "增值税普通发票" in full_text:
            result["invoice_type"] = "增值税普通发票"
        else:
            result["invoice_type"] = "未知"

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
    except Exception as e:
        raise HTTPException(400, detail=f"发票解析失败：{str(e)}")


@app.post("/merge")
async def merge_pdfs(files: List[UploadFile] = File(..., description="上传多个PDF文件")):
    """合并多个PDF"""
    if len(files) < 2:
        raise HTTPException(400, detail="至少需要上传2个PDF文件")

    writer = PdfWriter()
    total_pages = 0
    filenames = []

    for file in files:
        contents = validate_pdf(file)
        filenames.append(file.filename)
        try:
            reader = PdfReader(io.BytesIO(contents))
            for page in reader.pages:
                writer.add_page(page)
                total_pages += 1
        except Exception as e:
            raise HTTPException(400, detail=f"合并失败（{file.filename}）：{str(e)}")

    output = io.BytesIO()
    writer.write(output)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=merged.pdf"}
    )


@app.post("/split")
async def split_pdf(
        file: UploadFile = File(...),
        pages: str = Form(..., description="页码范围，如：1-3 或 5 或 1-3,5,7-9")
):
    """按页码范围拆分PDF"""
    contents = validate_pdf(file)

    try:
        reader = PdfReader(io.BytesIO(contents))
        total_pages = len(reader.pages)

        writer = PdfWriter()

        # 解析页码范围（支持：1-3,5,7-9）
        page_ranges = pages.split(',')
        selected_pages = []

        for pr in page_ranges:
            pr = pr.strip()
            if '-' in pr:
                start, end = pr.split('-')
                start = int(start)
                end = int(end)
                if start < 1 or end > total_pages or start > end:
                    raise HTTPException(400, detail=f"页码范围无效：{pr}（总页数：{total_pages}）")
                selected_pages.extend(range(start - 1, end))  # 0-based
            else:
                page = int(pr)
                if page < 1 or page > total_pages:
                    raise HTTPException(400, detail=f"页码无效：{page}（总页数：{total_pages}）")
                selected_pages.append(page - 1)

        # 去重并保持顺序
        seen = set()
        unique_pages = []
        for p in selected_pages:
            if p not in seen:
                seen.add(p)
                unique_pages.append(p)

        for i in unique_pages:
            writer.add_page(reader.pages[i])

        output = io.BytesIO()
        writer.write(output)
        output.seek(0)

        return StreamingResponse(
            output,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=split_{pages}.pdf"}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, detail=f"拆分失败：{str(e)}")


@app.get("/")
async def root():
    """首页重定向到前端"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/static/index.html")


@app.get("/api")
async def api_info():
    """API信息"""
    return {
        "service": "PDF工具箱",
        "version": "1.0.0",
        "endpoints": {
            "extract_text": {"url": "/extract/text", "method": "POST", "desc": "PDF转文本"},
            "extract_tables": {"url": "/extract/tables", "method": "POST", "desc": "提取表格"},
            "extract_invoice": {"url": "/extract/invoice", "method": "POST", "desc": "发票识别"},
            "merge": {"url": "/merge", "method": "POST", "desc": "合并PDF"},
            "split": {"url": "/split", "method": "POST", "desc": "拆分PDF"}
        },
        "docs": "/docs",
        "frontend": "/static/index.html"
    }
