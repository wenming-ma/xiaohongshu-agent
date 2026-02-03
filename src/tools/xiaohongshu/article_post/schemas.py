from pydantic import BaseModel


class XHSArticlePostInput(BaseModel):
    topic: str
    audience: str
    publish: bool = True


class XHSArticlePostOutput(BaseModel):
    success: bool
    title: str
    content: str
    hashtags: list[str]
    published: bool
    post_url: str | None
