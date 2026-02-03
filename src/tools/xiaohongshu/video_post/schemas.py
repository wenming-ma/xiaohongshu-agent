from pydantic import BaseModel


class XHSVideoPostInput(BaseModel):
    topic: str
    audience: str
    generate_video: bool = True
    publish: bool = True


class XHSVideoPostOutput(BaseModel):
    success: bool
    title: str
    hashtags: list[str]
    video_path: str | None
    published: bool
    post_url: str | None
