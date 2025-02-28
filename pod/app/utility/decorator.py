import inspect
from typing import Optional, Union, get_args, get_origin, get_type_hints

from fastapi import File, Form, UploadFile


def create_as_form_new(cls):
    fields = get_type_hints(cls)

    new_parameters = []
    for field_name, field_type in fields.items():
        is_optional = Optional in getattr(field_type, "__args__", [])

        if field_type == UploadFile or (hasattr(field_type, "__origin__") and field_type.__origin__ is UploadFile):
            param = File(None) if is_optional else File(...)
        else:
            param = Form(None) if is_optional else Form(...)

        new_parameters.append(
            inspect.Parameter(field_name, inspect.Parameter.KEYWORD_ONLY, default=param, annotation=field_type),
        )

    async def as_form_func(**data):
        return cls(**data)

    sig = inspect.signature(as_form_func)
    sig = sig.replace(parameters=new_parameters)
    as_form_func.__signature__ = sig
    return as_form_func


def create_as_form(cls):
    fields = get_type_hints(cls)

    new_parameters = []
    for field_name, field_type in fields.items():
        is_optional = Optional in getattr(field_type, "__args__", [])

        if field_type == UploadFile or (hasattr(field_type, "__origin__") and field_type.__origin__ is UploadFile):
            param = File(None) if is_optional else File(...)
        else:
            param = Form(None) if is_optional else Form(...)

        new_parameters.append(
            inspect.Parameter(field_name, inspect.Parameter.KEYWORD_ONLY, default=param, annotation=field_type),
        )

    async def as_form_func(**data):
        return cls(**data)

    sig = inspect.signature(as_form_func)
    sig = sig.replace(parameters=new_parameters)
    as_form_func.__signature__ = sig
    return as_form_func


def as_form_wrong(cls):
    new_parameters = []

    for field_name, field_info in cls.__fields__.items():
        field_type = field_info.annotation
        type_args = get_args(field_type)
        is_optional: bool = get_origin(field_type) is Union and type(None) in type_args

        if is_optional or field_info.default is not None:
            param = Form(field_info.default if field_info.default is not None else None)
        elif field_info.required:
            param = Form(...)
        else:
            param = Form(None)

        if UploadFile in type_args:
            param = File(None) if is_optional else File(...)

        new_parameters.append(inspect.Parameter(field_name, inspect.Parameter.KEYWORD_ONLY, default=param, annotation=field_type))

    async def as_form_func(**kwargs):
        return cls(**kwargs)

    sig = inspect.signature(as_form_func)
    sig = sig.replace(parameters=new_parameters)
    as_form_func.__signature__ = sig
    setattr(cls, "as_form", as_form_func)
    return cls


def as_form(cls):
    new_parameters = []

    for field_name, model_field in cls.__fields__.items():
        field_type = model_field.annotation

        type_args = get_args(field_type)
        is_optional = get_origin(field_type) is Union and type(None) in type_args

        if is_optional or model_field.default is not None:
            param = Form(model_field.default if model_field.default is not None else None)
        elif model_field.is_required:
            param = Form(...)
        else:
            param = Form(None)

        if UploadFile in type_args:
            if is_optional:
                param = File(None)
            else:
                param = File(...)

        new_parameters.append(
            inspect.Parameter(
                field_name,
                inspect.Parameter.KEYWORD_ONLY,
                default=param,
                annotation=field_type,
            )
        )

    async def as_form_func(**kwargs):
        return cls(**kwargs)

    sig = inspect.signature(as_form_func)
    sig = sig.replace(parameters=new_parameters)
    as_form_func.__signature__ = sig
    setattr(cls, 'as_form', as_form_func)
    return cls
