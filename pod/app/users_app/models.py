from tortoise import fields
from tortoise.models import Model


class BaseModel(Model):
    id = fields.UUIDField(primary_key=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        abstract = True

    def __str__(self):
        return "🚧 BaseModel"


class UserModel(BaseModel):
    first_name = fields.CharField(max_length=50, null=True)
    last_name = fields.CharField(max_length=50, null=True)
    username = fields.CharField(max_length=50, unique=True)
    email = fields.CharField(max_length=50, unique=True)
    password = fields.CharField(max_length=255)
    avatar = fields.CharField(max_length=255, null=True)
    banner = fields.CharField(max_length=255, null=True)
    banner_color = fields.CharField(max_length=6, null=True)
    birthdate = fields.DatetimeField(null=True)
    bio = fields.TextField(null=True)
    country = fields.CharField(max_length=200, null=True)
    is_admin = fields.BooleanField(default=False)
    is_blocked = fields.BooleanField(default=False)

    followers: fields.ReverseRelation["UserModel"]
    followings: fields.ReverseRelation["UserModel"]

    class Meta:
        table = "user"

    class PydanticMeta:
        allow_cycles = True
        exclude = ("password",)

    def __str__(self):
        return f"🚧 UserModel: {self.username}"

    def __repr__(self):
        return f"🚧 UserModel: {self.username}"
