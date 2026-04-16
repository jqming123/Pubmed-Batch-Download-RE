"""PDF format validation utilities"""

from typing import Optional

from PyPDF2 import PdfReader


def is_pdf_by_magic_number(content: bytes) -> bool:
    """
    检查内容是否为有效的PDF格式，通过检查PDF文件幻数。
    
    PDF文件的幻数是 %PDF，这是最可靠的识别方式，
    不受HTTP头和URL影响。
    
    Args:
        content: 文件内容的字节串
        
    Returns:
        True 如果内容以PDF文件签名开头，False 否则
    """
    return content.startswith(b"%PDF")


def get_pdf_page_count(pdf_file_path: str) -> Optional[int]:
    """
    获取PDF文件的页数。
    
    Args:
        pdf_file_path: PDF文件的完整路径
        
    Returns:
        PDF的页数，如果读取失败则返回None
    """
    try:
        with open(pdf_file_path, "rb") as pdf_file:
            pdf_reader = PdfReader(pdf_file)
            return len(pdf_reader.pages)
    except Exception:
        return None
