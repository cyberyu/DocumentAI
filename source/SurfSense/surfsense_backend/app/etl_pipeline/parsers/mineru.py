async def parse_with_mineru(file_path: str, filename: str) -> str:
    from app.services.mineru_service import create_mineru_service

    mineru_service = create_mineru_service()
    result = await mineru_service.process_document(file_path, filename)
    return result["content"]
