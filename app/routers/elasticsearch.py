from fastapi import APIRouter,UploadFile,File
from services.elasticsearch_service import query,upload,delete_docment,index_docment,update_docment,create_index,delete_index,get_docment
router = APIRouter(prefix="/elasticsearch", tags=["Elasticsearch接口"])

@router.post("/search")
async def search(
    query1:str):
    return query(query1)

@router.post("/add_file")
async def add_file(
    file:UploadFile=File(...)):
    upload(file)
    return {"message": "File uploaded successfully"}

@router.post("/create_index")
async def create_index1(
    index:str
):
    return create_index(index)

@router.post("/index_docment")
async def index_docment1(
    index:str,
    id:str
):
    return index_docment(index, id)

@router.post("/update_docment")
async def update_docment1(
    index:str,
    id:str
):
    return update_docment(index, id)

@router.post("/delete_docment")
async def delete_docment1(
    index:str,
    id:str
):
    return delete_docment(index, id)

@router.post("/delete_index")
async def delete_index1(
    index:str
):
    return delete_index(index)


@router.post("/get_docment")
async def get_docment1(
    index:str,
    id:str
):
    return get_docment(index, id)