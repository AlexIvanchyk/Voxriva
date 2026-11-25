"""Reusable fictional Northstar templates and original local image assets.

No installation identifiers, credentials, encrypted state or remote downloads.
Both the first-email example and the richer demo use this fixture.
"""

import base64
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"


def image(name):
    return {
        "media_type": "image/png",
        "content_base64": base64.b64encode((ASSETS / name).read_bytes()).decode(),
    }


def email_draft(locale="en"):
    uk = locale == "uk"
    headline = (
        "Раді бачити вас, {{ first_name }}."
        if uk
        else "You’re in good company, {{ first_name }}."
    )
    intro = (
        "Дякуємо, що обрали Northstar. Ми зібрали продумані речі для щоденного життя."
        if uk
        else "Welcome to a slower, more thoughtful way to shop. Discover useful things, made to be kept."
    )
    return {
        "subject": "Вітаємо у Northstar, {{ first_name }}"
        if uk
        else "A warm welcome to Northstar, {{ first_name }}",
        "text": f"{headline}\n{intro}\n{{{{ account_url }}}}\nQuestions? {{{{ phone }}}}",
        "html": '<div style="background:#f2f4ef;padding:24px;font-family:Arial,sans-serif;color:#133f3a"><div style="max-width:560px;margin:auto;background:white;border-radius:16px;overflow:hidden"><div style="padding:28px"><img src="voxriva-image:logo" alt="Northstar Market" width="210"></div><img src="{{ banner }}" alt="Thoughtful everyday essentials" width="560" style="display:block;max-width:100%"><div style="padding:32px"><p style="font-size:11px;letter-spacing:2px;color:#718578">WELCOME TO YOUR NORTHSTAR</p><h1 style="font-size:29px;line-height:1.2">'
        + headline
        + '</h1><p style="font-size:16px;line-height:1.7;color:#59685d">'
        + intro
        + '</p><p style="margin:28px 0"><a href="{{ account_url }}" style="display:inline-block;background:#133f3a;color:white;padding:15px 24px;border-radius:8px;text-decoration:none">'
        + ("Відкрити мій простір" if uk else "Explore your account")
        + '</a></p><p style="font-size:13px;color:#718578">Need a hand? {{ phone }}<br>Northstar Market · Fictional demo brand</p></div></div><p style="text-align:center;font-size:11px;color:#718578">Local demonstration · No real purchase or cloud delivery</p></div>',
        "images": {"logo": image("northstar-logo.png")},
        "variable_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "first_name": {"type": "string", "minLength": 1},
                "account_url": {"type": "string", "format": "uri"},
                "phone": {
                    "type": "string",
                    "format": "phone",
                    "x-voxriva-phone-version": 1,
                },
                "banner": {
                    "type": "object",
                    "x-voxriva-image": 1,
                    "properties": {
                        "media_type": {
                            "type": "string",
                            "enum": ["image/png", "image/jpeg", "image/webp"],
                        },
                        "content_base64": {"type": "string", "maxLength": 349528},
                    },
                    "required": ["media_type", "content_base64"],
                    "additionalProperties": False,
                },
            },
            "required": ["first_name", "account_url", "phone", "banner"],
            "additionalProperties": False,
        },
        "runtime_defaults": {
            "banner": image("northstar-welcome.png"),
            "phone": "+12025550142",
        },
        "preview_context": {
            "first_name": "Софія" if uk else "Sofia",
            "account_url": "https://northstar.example.test/account",
        },
        "scenarios": {
            "New customer": {
                "first_name": "Alex",
                "account_url": "https://northstar.example.test/account",
            },
            "Seasonal banner": {
                "first_name": "Jordan",
                "account_url": "https://northstar.example.test/account",
                "banner": image("northstar-seasonal.png"),
            },
        },
    }
