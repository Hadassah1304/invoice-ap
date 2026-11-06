EXTRACTION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "vendor": {
            "type": "OBJECT",
            "properties": {
                "name": {"type": "STRING", "nullable": True},
                "gstin": {"type": "STRING", "nullable": True},
                "email": {"type": "STRING", "nullable": True},
                "phone": {"type": "STRING", "nullable": True},
                "address": {"type": "STRING", "nullable": True},
                "bank_account": {"type": "STRING", "nullable": True},
                "confidence": {"type": "NUMBER"},
            },
            "required": ["confidence"],
        },
        "invoice_number": {
            "type": "OBJECT",
            "properties": {
                "value": {"type": "STRING", "nullable": True},
                "confidence": {"type": "NUMBER"},
            },
            "required": ["confidence"],
        },
        "invoice_date": {
            "type": "OBJECT",
            "properties": {
                "value": {"type": "STRING", "nullable": True},
                "confidence": {"type": "NUMBER"},
                "ambiguous": {"type": "BOOLEAN", "nullable": True},
            },
            "required": ["confidence"],
        },
        "due_date": {
            "type": "OBJECT",
            "properties": {
                "value": {"type": "STRING", "nullable": True},
                "confidence": {"type": "NUMBER"},
            },
        },
        "po_reference": {
            "type": "OBJECT",
            "properties": {
                "value": {"type": "STRING", "nullable": True},
                "confidence": {"type": "NUMBER"},
            },
        },
        "currency": {
            "type": "OBJECT",
            "properties": {
                "value": {"type": "STRING", "nullable": True},
                "confidence": {"type": "NUMBER"},
            },
            "required": ["confidence"],
        },
        "line_items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "line_no": {"type": "INTEGER", "nullable": True},
                    "description": {"type": "STRING", "nullable": True},
                    "quantity": {"type": "NUMBER", "nullable": True},
                    "uom": {"type": "STRING", "nullable": True},
                    "unit_price": {"type": "NUMBER", "nullable": True},
                    "line_total": {"type": "NUMBER", "nullable": True},
                    "tax_rate": {"type": "NUMBER", "nullable": True},
                    "confidence": {"type": "NUMBER"},
                },
                "required": ["description", "confidence"],
            },
        },
        "subtotal": {
            "type": "OBJECT",
            "properties": {
                "value": {"type": "NUMBER", "nullable": True},
                "confidence": {"type": "NUMBER"},
            },
        },
        "tax_total": {
            "type": "OBJECT",
            "properties": {
                "value": {"type": "NUMBER", "nullable": True},
                "confidence": {"type": "NUMBER"},
            },
        },
        "grand_total": {
            "type": "OBJECT",
            "properties": {
                "value": {"type": "NUMBER", "nullable": True},
                "confidence": {"type": "NUMBER"},
            },
            "required": ["confidence"],
        },
        "document_type": {
            "type": "STRING",
            "enum": ["invoice", "credit_note", "debit_note", "proforma", "other"],
        },
    },
    "required": [
        "vendor",
        "invoice_number",
        "invoice_date",
        "currency",
        "line_items",
        "grand_total",
        "document_type",
    ],
}
