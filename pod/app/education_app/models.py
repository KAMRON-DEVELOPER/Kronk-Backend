from app.users_app.models import BaseModel, UserModel
from tortoise import fields


class TabModel(BaseModel):
    title = fields.CharField(max_length=30)
    owner: fields.ForeignKeyRelation[UserModel] = fields.ForeignKeyField(model_name="users_app.UserModel", related_name="tabs", to_field="id")

    class Meta:
        table = "tab"

    def __str__(self):
        return f"🚧 <{self.__class__.__name__}: {self.title}>"

    def __repr__(self):
        return f"🚧 <{self.__class__.__name__}: {self.title}>"


class NoteModel(BaseModel):
    title = fields.CharField(max_length=50)
    body = fields.TextField()
    is_pinned = fields.BooleanField(default=False)
    color = fields.CharField(max_length=6, null=True)
    tab = fields.ForeignKeyField(model_name="education_app.TabModel", related_name="notes", to_field="id")

    class Meta:
        table = "note"

    def __str__(self):
        return f"🚧 <{self.__class__.__name__}: {self.title}>"

    def __repr__(self):
        return f"🚧 <{self.__class__.__name__}: {self.title}>"


class ImageModel(BaseModel):
    user: fields.ForeignKeyRelation[UserModel] = fields.ForeignKeyField(model_name="users_app.UserModel", related_name="images", to_field="id")
    file_path = fields.CharField(max_length=50)
    language_from = fields.CharField(max_length=50, default="en")
    language_to = fields.CharField(max_length=50, default="uz")
    extracted_text = fields.TextField()
    is_incomplete_sentence = fields.BooleanField(default=False)

    class Meta:
        table = "image"

    def __str__(self):
        return f"🚧 <{self.__class__.__name__}: {self.file_path}>"

    def __repr__(self):
        return f"🚧 <{self.__class__.__name__}: {self.file_path}>"


class VocabularyModel(BaseModel):
    image = fields.ForeignKeyField(model_name="education_app.ImageModel", related_name="vocabularies")
    word = fields.CharField(max_length=255)
    translation = fields.CharField(max_length=255)
    definition = fields.TextField(null=True)
    part_of_speech = fields.CharField(max_length=50)
    examples = fields.JSONField(null=True)
    synonyms = fields.JSONField(null=True)
    transcription = fields.CharField(max_length=255, null=True)
    audio_pronunciation_url = fields.CharField(max_length=255)
    tab = fields.ForeignKeyField(model_name="education_app.TabModel", related_name="vocabularies", to_field="id")

    class Meta:
        table = "vocabulary"

    def __str__(self):
        return f"🚧 <{self.__class__.__name__}: {self.word}>"

    def __repr__(self):
        return f"🚧 <{self.__class__.__name__}: {self.word}>"


class SentenceModel(BaseModel):
    image = fields.ForeignKeyField(model_name="education_app.ImageModel", related_name="sentences", to_field="id")
    body = fields.TextField()
    translation = fields.TextField()
    tab = fields.ForeignKeyField(model_name="education_app.TabModel", related_name="sentences", to_field="id")

    class Meta:
        table = "sentence"

    def __str__(self):
        return f"🚧 <{self.__class__.__name__}: {self.body[:8]}>"

    def __repr__(self):
        return f"🚧 <{self.__class__.__name__}: {self.body[:8]}>"
