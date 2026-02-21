"""
FieldKey Voice-First Locksmith Assistant — FastAPI Backend
Wraps main.py hybrid routing + Cactus Whisper transcription
"""

import sys, os, json, time, tempfile, uuid, re as _re, asyncio, concurrent.futures, subprocess, threading
sys.path.insert(0, "cactus/python/src")

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from main import generate_hybrid
from cactus import cactus_init, cactus_transcribe, cactus_reset

# ══════════════════════════════════════════════════════════════════════
# WHISPER MODEL
# ══════════════════════════════════════════════════════════════════════

WHISPER_MODEL_PATH = "cactus/weights/whisper-small"
_whisper_model = None

def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        if os.path.exists(WHISPER_MODEL_PATH):
            _whisper_model = cactus_init(WHISPER_MODEL_PATH)
        else:
            print(f"[WARN] Whisper model not found at {WHISPER_MODEL_PATH}")
    return _whisper_model


# ══════════════════════════════════════════════════════════════════════
# LOCKSMITH TOOL DEFINITIONS
# ══════════════════════════════════════════════════════════════════════

LOCKSMITH_TOOLS = [
    {
        "name": "diagnose_lock_fault",
        "description": "Diagnose a lock or door hardware fault based on symptoms described by the locksmith",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "Door or lock location (e.g. front door, garage, unit 4B)"},
                "symptoms": {"type": "string", "description": "Observed symptoms (e.g. jammed, won't turn, loose cylinder)"},
                "lock_type": {"type": "string", "description": "Type of lock if known (e.g. deadbolt, knob lock, mortise, padlock)"},
            },
            "required": ["location", "symptoms"],
        },
    },
    {
        "name": "log_service_report",
        "description": "Log a completed service report for a locksmith job",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_name": {"type": "string", "description": "Customer name"},
                "service_type": {"type": "string", "description": "Type of service performed (e.g. rekey, lock change, lockout, install)"},
                "notes": {"type": "string", "description": "Additional notes about the job"},
            },
            "required": ["customer_name", "service_type"],
        },
    },
    {
        "name": "generate_checklist",
        "description": "Generate a pre-job or safety checklist for a locksmith task",
        "parameters": {
            "type": "object",
            "properties": {
                "job_type": {"type": "string", "description": "Type of job (e.g. residential rekey, commercial install, auto lockout)"},
            },
            "required": ["job_type"],
        },
    },
    {
        "name": "lookup_part",
        "description": "Look up a lock part, key blank, or hardware component by name or model number",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Part name or model number to search for"},
                "brand": {"type": "string", "description": "Brand name if known (e.g. Schlage, Kwikset, Yale)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "schedule_followup",
        "description": "Schedule a follow-up appointment with a customer",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_name": {"type": "string", "description": "Customer name"},
                "date": {"type": "string", "description": "Preferred date (e.g. next Tuesday, March 15)"},
                "reason": {"type": "string", "description": "Reason for follow-up"},
            },
            "required": ["customer_name", "date"],
        },
    },
    {
        "name": "contact_dispatch",
        "description": "Contact dispatch for backup, additional tools, or emergency coordination",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Reason for contacting dispatch"},
                "urgency": {"type": "string", "description": "Urgency level: low, medium, high, emergency"},
            },
            "required": ["reason"],
        },
    },
    {
        "name": "generate_invoice",
        "description": "Generate a professional PDF invoice for a completed locksmith service job",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_name": {"type": "string", "description": "Customer name for the invoice"},
                "service_type": {"type": "string", "description": "Type of service performed (e.g. rekey, lock change, lockout, install)"},
                "amount": {"type": "string", "description": "Total amount to charge (e.g. $150.00)"},
                "notes": {"type": "string", "description": "Additional line items or notes"},
            },
            "required": ["customer_name", "service_type"],
        },
    },
]


# ══════════════════════════════════════════════════════════════════════
# MOCK TOOL EXECUTION
# ══════════════════════════════════════════════════════════════════════

def execute_tool(name: str, arguments: dict) -> dict:
    """Execute a locksmith tool with mock results for demo purposes."""

    if name == "diagnose_lock_fault":
        location = arguments.get("location", "door")
        symptoms = arguments.get("symptoms", "issue")
        lock_type = arguments.get("lock_type", "deadbolt")
        return {
            "diagnosis": f"Likely worn tailpiece or misaligned strike plate",
            "location": location,
            "symptoms_confirmed": symptoms,
            "lock_type": lock_type,
            "recommended_action": "Remove cylinder, inspect tailpiece for wear. Check strike plate alignment with 1/8\" tolerance.",
            "estimated_time": "25-35 minutes",
            "parts_needed": ["Replacement tailpiece", "Strike plate shims"],
            "difficulty": "moderate",
        }

    elif name == "log_service_report":
        return {
            "status": "logged",
            "report_id": f"SR-{uuid.uuid4().hex[:8].upper()}",
            "customer": arguments.get("customer_name", ""),
            "service": arguments.get("service_type", ""),
            "timestamp": time.strftime("%Y-%m-%d %H:%M"),
            "notes": arguments.get("notes", "No additional notes"),
        }

    elif name == "generate_checklist":
        job_type = arguments.get("job_type", "general").lower()
        checklists = {
            "residential rekey": [
                "Verify customer ID and ownership/authorization",
                "Count total locks to be rekeyed",
                "Check existing keyway (SC1, KW1, etc.)",
                "Prepare pinning kit with correct depths",
                "Test all locks before and after rekey",
                "Provide new keys and test each one",
                "Document key bitting for records",
            ],
            "commercial install": [
                "Review building codes and fire marshal requirements",
                "Verify door prep dimensions",
                "Check for ADA compliance requirements",
                "Confirm master key system compatibility",
                "Install hardware per manufacturer specs",
                "Test panic hardware and auto-closers",
                "Provide documentation to building manager",
            ],
            "auto lockout": [
                "Verify vehicle ownership (registration/ID)",
                "Identify vehicle make, model, and year",
                "Select appropriate entry tool",
                "Protect paint and weather stripping",
                "Attempt non-destructive entry first",
                "Test all doors after entry",
                "Document any pre-existing damage",
            ],
        }
        items = checklists.get(job_type, [
            "Verify job scope with customer",
            "Inspect existing hardware",
            "Prepare tools and parts",
            "Perform service",
            "Test and verify completion",
            "Clean work area",
            "Collect payment and provide receipt",
        ])
        return {"job_type": job_type, "checklist": items}

    elif name == "lookup_part":
        query = arguments.get("query", "")
        brand = arguments.get("brand", "Generic")
        return {
            "part": query,
            "brand": brand,
            "found": True,
            "description": f"{brand} {query}",
            "price_range": "$4.50 - $12.00",
            "in_stock": True,
            "compatible_models": ["B60N", "B62N", "B560P"],
            "supplier": "Lock Supply Co.",
            "notes": "Standard 6-pin key blank, available in brass and nickel silver",
        }

    elif name == "schedule_followup":
        return {
            "status": "scheduled",
            "appointment_id": f"APT-{uuid.uuid4().hex[:6].upper()}",
            "customer": arguments.get("customer_name", ""),
            "date": arguments.get("date", ""),
            "reason": arguments.get("reason", "Follow-up service"),
            "confirmation": "Customer will receive SMS confirmation",
        }

    elif name == "contact_dispatch":
        urgency = arguments.get("urgency", "medium")
        return {
            "status": "dispatched",
            "dispatch_id": f"DSP-{uuid.uuid4().hex[:6].upper()}",
            "reason": arguments.get("reason", ""),
            "urgency": urgency,
            "eta": "10-15 minutes" if urgency in ("high", "emergency") else "20-30 minutes",
            "dispatcher": "Central Dispatch",
            "confirmation": "Dispatch notified and backup en route",
        }

    elif name == "generate_invoice":
        invoice_id = f"INV-{uuid.uuid4().hex[:6].upper()}"
        customer = arguments.get("customer_name", "Customer")
        service = arguments.get("service_type", "Locksmith Service")
        amount = arguments.get("amount", "$150.00")
        notes = arguments.get("notes", "")

        # Generate actual PDF
        pdf_path = _generate_invoice_pdf(invoice_id, customer, service, amount, notes)

        return {
            "status": "generated",
            "invoice_id": invoice_id,
            "customer": customer,
            "service": service,
            "amount": amount,
            "pdf_url": f"/api/invoice/{invoice_id}",
            "timestamp": time.strftime("%Y-%m-%d %H:%M"),
        }

    return {"error": f"Unknown tool: {name}"}


# ══════════════════════════════════════════════════════════════════════
# PDF INVOICE GENERATION
# ══════════════════════════════════════════════════════════════════════

INVOICE_DIR = os.path.join(tempfile.gettempdir(), "fieldkey_invoices")
os.makedirs(INVOICE_DIR, exist_ok=True)


def _generate_invoice_pdf(invoice_id, customer, service, amount, notes=""):
    """Generate a professional locksmith invoice PDF."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Header bar
    pdf.set_fill_color(30, 30, 46)
    pdf.rect(0, 0, 210, 40, 'F')
    pdf.set_text_color(255, 107, 53)
    pdf.set_font("Helvetica", "B", 24)
    pdf.set_xy(15, 10)
    pdf.cell(0, 12, "FieldKey", ln=True)
    pdf.set_text_color(200, 200, 200)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_x(15)
    pdf.cell(0, 6, "Professional Locksmith Services", ln=True)

    # Invoice ID + date (right side)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_xy(130, 12)
    pdf.cell(65, 7, f"Invoice: {invoice_id}", align="R")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_xy(130, 20)
    pdf.cell(65, 7, f"Date: {time.strftime('%B %d, %Y')}", align="R")

    # Reset for body
    pdf.set_text_color(30, 30, 30)
    pdf.ln(20)

    # Bill To
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 8, "BILL TO", ln=True)
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 7, customer, ln=True)
    pdf.ln(10)

    # Table header
    pdf.set_fill_color(245, 245, 245)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(100, 10, "  Description", border=1, fill=True)
    pdf.cell(30, 10, "Qty", border=1, align="C", fill=True)
    pdf.cell(50, 10, "Amount", border=1, align="R", fill=True)
    pdf.ln()

    # Service line item
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(100, 10, f"  {service.title()}", border=1)
    pdf.cell(30, 10, "1", border=1, align="C")
    pdf.cell(50, 10, f"{amount}  ", border=1, align="R")
    pdf.ln()

    # Service call fee
    pdf.cell(100, 10, "  Service Call Fee", border=1)
    pdf.cell(30, 10, "1", border=1, align="C")
    pdf.cell(50, 10, "$45.00  ", border=1, align="R")
    pdf.ln()

    # Parts if applicable
    if "rekey" in service.lower() or "change" in service.lower() or "install" in service.lower():
        pdf.cell(100, 10, "  Parts & Materials", border=1)
        pdf.cell(30, 10, "1", border=1, align="C")
        pdf.cell(50, 10, "$35.00  ", border=1, align="R")
        pdf.ln()

    # Total
    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(130, 10, "")
    pdf.cell(50, 10, f"TOTAL: {amount}", align="R")
    pdf.ln(15)

    # Notes
    if notes:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 8, "NOTES", ln=True)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(0, 6, notes)
        pdf.ln(10)

    # Footer
    pdf.set_y(-40)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 5, "Payment due within 30 days. Thank you for your business!", align="C", ln=True)
    pdf.cell(0, 5, "FieldKey Locksmith Services | support@fieldkey.app | (555) 123-4567", align="C", ln=True)

    path = os.path.join(INVOICE_DIR, f"{invoice_id}.pdf")
    pdf.output(path)
    return path


# ══════════════════════════════════════════════════════════════════════
# KEYWORD FALLBACK — when hybrid routing is unavailable
# ══════════════════════════════════════════════════════════════════════

def _keyword_fallback(messages, tools):
    """Simple keyword-based tool matching when model routing is unavailable."""
    user_text = " ".join(m["content"] for m in messages if m.get("role") == "user")
    text_lower = user_text.lower()
    start = time.time()

    patterns = [
        (r'diagnos|jammed|stuck|broken|won.?t turn|fault|malfunction|not working|lock issue',
         "diagnose_lock_fault", lambda t: _extract_diagnose_args(t), False),
        (r'log\s+service|service\s+report|report\s+for|completed|finished\s+job',
         "log_service_report", lambda t: _extract_report_args(t), False),
        (r'checklist|pre.?job|safety\s+check',
         "generate_checklist", lambda t: _extract_checklist_args(t), False),
        (r'look\s*up|part|key\s*blank|hardware|component|model\s+number',
         "lookup_part", lambda t: _extract_part_args(t), False),
        (r'schedule|follow.?up|appointment|next\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)',
         "schedule_followup", lambda t: _extract_followup_args(t), False),
        (r'dispatch|backup|emergency|reinforcement|send\s+help',
         "contact_dispatch", lambda t: _extract_dispatch_args(t), False),
        (r'invoice|bill|charge|receipt|payment',
         "generate_invoice", lambda t: _extract_invoice_args(t), True),
    ]

    tool_names = {t["name"] for t in tools}
    calls = []
    needs_cloud = False

    for pattern, tool_name, extractor, is_cloud in patterns:
        if tool_name in tool_names and _re.search(pattern, text_lower):
            args = extractor(user_text)
            calls.append({"name": tool_name, "arguments": args})
            if is_cloud:
                needs_cloud = True

    elapsed = (time.time() - start) * 1000
    return {
        "function_calls": calls,
        "total_time_ms": elapsed,
        "source": "cloud" if needs_cloud else "on-device",
    }


def _extract_diagnose_args(text):
    args = {"symptoms": text}
    loc_match = _re.search(r'(?:on|at|for)\s+(?:the\s+)?(.+?(?:door|lock|gate|entrance|exit))', text, _re.IGNORECASE)
    if loc_match:
        args["location"] = loc_match.group(1).strip()
    type_match = _re.search(r'(deadbolt|knob\s*lock|mortise|padlock|smart\s*lock|lever|cylinder)', text, _re.IGNORECASE)
    if type_match:
        args["lock_type"] = type_match.group(1).strip()
    return args


def _extract_report_args(text):
    args = {"service_type": "service"}
    name_match = _re.search(r'(?:for|customer|client)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', text)
    if name_match:
        args["customer_name"] = name_match.group(1).strip()
    else:
        args["customer_name"] = "Customer"
    svc_match = _re.search(r'(rekey|lockout|lock\s*change|install|repair|master\s*key)', text, _re.IGNORECASE)
    if svc_match:
        args["service_type"] = svc_match.group(1).strip()
    return args


def _extract_checklist_args(text):
    jt_match = _re.search(r'(residential\s+rekey|commercial\s+install|auto\s+lockout|rekey|lockout|install)', text, _re.IGNORECASE)
    return {"job_type": jt_match.group(1).strip() if jt_match else "general"}


def _extract_part_args(text):
    args = {"query": text}
    part_match = _re.search(r'(?:look\s*up|find|search\s+for)\s+(?:a\s+)?(.+?)(?:\s+for|\s*$)', text, _re.IGNORECASE)
    if part_match:
        args["query"] = part_match.group(1).strip().rstrip('.')
    brand_match = _re.search(r'(Schlage|Kwikset|Yale|Medeco|Mul-T-Lock|Baldwin|Sargent)', text, _re.IGNORECASE)
    if brand_match:
        args["brand"] = brand_match.group(1).strip()
    return args


def _extract_followup_args(text):
    args = {"date": "TBD"}
    name_match = _re.search(r'(?:with|for)\s+(?:Mrs?\.?\s+|Ms\.?\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', text)
    if name_match:
        args["customer_name"] = name_match.group(0).replace("with ", "").replace("for ", "").strip()
    else:
        args["customer_name"] = "Customer"
    date_match = _re.search(r'(next\s+\w+|tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\w+\s+\d{1,2})', text, _re.IGNORECASE)
    if date_match:
        args["date"] = date_match.group(1).strip()
    reason_match = _re.search(r'(?:for|to|about)\s+(.+?)(?:\s+next|\s+on|\s*$)', text, _re.IGNORECASE)
    if reason_match:
        args["reason"] = reason_match.group(1).strip()
    return args


def _extract_dispatch_args(text):
    args = {"reason": text}
    reason_match = _re.search(r'(?:need|require|requesting)\s+(.+?)(?:\.|$)', text, _re.IGNORECASE)
    if reason_match:
        args["reason"] = reason_match.group(1).strip()
    if _re.search(r'emergency|urgent|asap|immediately', text, _re.IGNORECASE):
        args["urgency"] = "emergency"
    elif _re.search(r'backup|help|assist', text, _re.IGNORECASE):
        args["urgency"] = "high"
    else:
        args["urgency"] = "medium"
    return args


def _extract_invoice_args(text):
    args = {"service_type": "Locksmith Service"}
    # Name: match "for Sarah Miller" or "customer Sarah Miller" etc.
    name_match = _re.search(r'(?:for|customer|client)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', text)
    if name_match:
        args["customer_name"] = name_match.group(1).strip()
    else:
        # Fallback: look for any two consecutive capitalized words
        cap_match = _re.search(r'(?<!\w)([A-Z][a-z]+\s+[A-Z][a-z]+)', text)
        if cap_match:
            args["customer_name"] = cap_match.group(1).strip()
        else:
            args["customer_name"] = "Customer"
    # Service type
    svc_match = _re.search(r'(rekey(?:ing)?|lockout|lock\s*change|install(?:ation)?|repair|master\s*key|deadbolt|lock\s+replacement)', text, _re.IGNORECASE)
    if svc_match:
        args["service_type"] = svc_match.group(1).strip()
    # Amount: match $250, $250.00, $1,250.00 etc.
    amt_match = _re.search(r'\$[\d,]+(?:\.\d{2})?', text)
    if amt_match:
        raw = amt_match.group(0)
        # Normalize: add .00 if no decimal
        if '.' not in raw:
            raw += '.00'
        args["amount"] = raw
    else:
        args["amount"] = "$150.00"
    notes_match = _re.search(r'(?:notes?|memo|description)\s*:?\s*(.+?)(?:\.|$)', text, _re.IGNORECASE)
    if notes_match:
        args["notes"] = notes_match.group(1).strip()
    return args


# ══════════════════════════════════════════════════════════════════════
# ARGUMENT ENRICHMENT — fill in missing args from regex extraction
# ══════════════════════════════════════════════════════════════════════

_EXTRACTORS = {
    "diagnose_lock_fault": _extract_diagnose_args,
    "log_service_report": _extract_report_args,
    "generate_checklist": _extract_checklist_args,
    "lookup_part": _extract_part_args,
    "schedule_followup": _extract_followup_args,
    "contact_dispatch": _extract_dispatch_args,
    "generate_invoice": _extract_invoice_args,
}

# Values that indicate the model returned empty/default args
_DEFAULT_VALUES = {"", "Customer", "Locksmith Service", "unknown", "none", "N/A"}


def _enrich_arguments(name, args, user_text):
    """Enrich function call arguments with keyword extraction for missing values."""
    extractor = _EXTRACTORS.get(name)
    if extractor is None:
        return args
    extracted = extractor(user_text)
    for key, value in extracted.items():
        existing = args.get(key, "")
        if not existing or str(existing).strip() in _DEFAULT_VALUES:
            args[key] = value
    return args


# ══════════════════════════════════════════════════════════════════════
# JOB HISTORY — in-memory session store
# ══════════════════════════════════════════════════════════════════════

_job_history: list[dict] = []


# ══════════════════════════════════════════════════════════════════════
# FASTAPI APP
# ══════════════════════════════════════════════════════════════════════

app = FastAPI(title="FieldKey Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class HybridRequest(BaseModel):
    messages: list[dict]
    tools: Optional[list[dict]] = None


@app.get("/api/health")
async def health():
    whisper_ok = os.path.exists(WHISPER_MODEL_PATH)
    return {"status": "ok", "whisper_available": whisper_ok}


@app.get("/api/history")
async def get_history(tool: Optional[str] = None):
    """Get job history, optionally filtered by tool name."""
    if tool:
        filtered = [h for h in _job_history if h.get("name") == tool]
        return {"history": filtered, "count": len(filtered)}
    return {"history": _job_history, "count": len(_job_history)}


@app.get("/api/invoice/{invoice_id}")
async def get_invoice(invoice_id: str):
    """Serve a generated invoice PDF."""
    path = os.path.join(INVOICE_DIR, f"{invoice_id}.pdf")
    if not os.path.exists(path):
        return {"error": "Invoice not found"}
    return FileResponse(path, media_type="application/pdf", filename=f"{invoice_id}.pdf")


@app.post("/api/hybrid")
async def hybrid_endpoint(req: HybridRequest):
    """Run hybrid routing (edge/cloud) on locksmith tools."""
    tools = req.tools or LOCKSMITH_TOOLS
    start = time.time()

    try:
        result = generate_hybrid(req.messages, tools)
    except Exception as e:
        print(f"[WARN] generate_hybrid failed: {e}")
        result = _keyword_fallback(req.messages, tools)

    # Always use wall-clock time so UI shows real latency
    elapsed = (time.time() - start) * 1000

    # Enrich arguments with regex extraction for any missing values
    user_text = " ".join(m["content"] for m in req.messages if m.get("role") == "user")
    for call in result.get("function_calls", []):
        call["arguments"] = _enrich_arguments(
            call["name"], call.get("arguments", {}), user_text
        )

    # Execute each function call with mock tools
    executed = []
    for call in result.get("function_calls", []):
        tool_result = execute_tool(call["name"], call["arguments"])
        entry = {
            "name": call["name"],
            "arguments": call["arguments"],
            "result": tool_result,
        }
        executed.append(entry)
        # Store in history
        _job_history.append({
            **entry,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": result.get("source", "unknown"),
            "latency_ms": round(elapsed, 1),
        })

    return {
        "function_calls": executed,
        "source": result.get("source", "unknown"),
        "latency_ms": round(elapsed, 1),
    }


_thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)


def _convert_to_wav(input_path: str) -> str:
    """Convert any audio file to 16kHz mono WAV using ffmpeg."""
    wav_path = input_path.rsplit(".", 1)[0] + ".wav"
    print(f"[DEBUG] Converting {input_path} -> {wav_path}", flush=True)
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", input_path, "-ar", "16000", "-ac", "1", "-f", "wav", wav_path],
            capture_output=True, timeout=10,
        )
        if r.returncode != 0:
            print(f"[WARN] ffmpeg error: {r.stderr.decode()[:200]}", flush=True)
        if os.path.exists(wav_path) and os.path.getsize(wav_path) > 0:
            print(f"[DEBUG] Converted OK: {os.path.getsize(wav_path)} bytes", flush=True)
            return wav_path
    except Exception as e:
        print(f"[WARN] ffmpeg conversion failed: {e}", flush=True)
    return input_path  # fallback to original


_whisper_lock = threading.Lock()


def _do_transcribe(whisper, audio_path: str) -> tuple:
    """Run transcription in a thread (blocking). Uses lock for thread safety."""
    # Convert to WAV if not already
    wav_path = audio_path
    if not audio_path.endswith(".wav"):
        wav_path = _convert_to_wav(audio_path)

    with _whisper_lock:
        cactus_reset(whisper)  # Clear KV cache between transcriptions
        start = time.time()
        prompt = "<|startoftranscript|><|en|><|transcribe|><|notimestamps|>"
        raw = cactus_transcribe(whisper, wav_path, prompt=prompt)
        elapsed = (time.time() - start) * 1000

    result = json.loads(raw) if isinstance(raw, str) else raw
    text = (result.get("response") or "").strip() if isinstance(result, dict) else ""
    print(f"[DEBUG] Transcription result: '{text}' ({elapsed:.0f}ms)", flush=True)

    # Cleanup converted file
    if wav_path != audio_path and os.path.exists(wav_path):
        os.unlink(wav_path)

    return text, elapsed


@app.post("/api/transcribe")
async def transcribe_endpoint(audio: UploadFile = File(...)):
    """Transcribe audio using on-device Whisper."""
    loop = asyncio.get_event_loop()
    whisper = await loop.run_in_executor(_thread_pool, _get_whisper)
    if whisper is None:
        return {"error": "Whisper model not available", "text": ""}

    # Save uploaded file
    ext = os.path.splitext(audio.filename or "audio.wav")[1] or ".wav"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        content = await audio.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        text, elapsed = await loop.run_in_executor(
            _thread_pool, _do_transcribe, whisper, tmp_path
        )
        return {"text": text, "latency_ms": round(elapsed, 1)}
    except Exception as e:
        return {"error": str(e), "text": ""}
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.post("/api/process_voice")
async def process_voice_endpoint(audio: UploadFile = File(...)):
    """Combined: transcribe audio then run hybrid routing."""
    loop = asyncio.get_event_loop()
    whisper = await loop.run_in_executor(_thread_pool, _get_whisper)

    # Step 1: Transcribe
    transcribe_text = ""
    transcribe_ms = 0

    if whisper is not None:
        ext = os.path.splitext(audio.filename or "audio.m4a")[1] or ".m4a"
        print(f"[DEBUG] Voice upload: filename={audio.filename}, ext={ext}", flush=True)
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            content = await audio.read()
            tmp.write(content)
            tmp_path = tmp.name

        try:
            transcribe_text, transcribe_ms = await loop.run_in_executor(
                _thread_pool, _do_transcribe, whisper, tmp_path
            )
        except Exception as e:
            print(f"[WARN] Transcription failed: {e}", flush=True)
            transcribe_text = ""
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    else:
        # Read audio but return empty transcription
        await audio.read()
        transcribe_text = ""

    if not transcribe_text:
        return {
            "transcription": "",
            "transcribe_latency_ms": round(transcribe_ms, 1),
            "function_calls": [],
            "source": "none",
            "routing_latency_ms": 0,
        }

    # Step 2: Hybrid routing (with fallback)
    messages = [{"role": "user", "content": transcribe_text}]
    start = time.time()
    try:
        hybrid_result = generate_hybrid(messages, LOCKSMITH_TOOLS)
    except Exception as e:
        print(f"[WARN] generate_hybrid failed in voice: {e}", flush=True)
        hybrid_result = _keyword_fallback(messages, LOCKSMITH_TOOLS)
    routing_ms = (time.time() - start) * 1000

    # Enrich arguments
    for call in hybrid_result.get("function_calls", []):
        call["arguments"] = _enrich_arguments(
            call["name"], call.get("arguments", {}), transcribe_text
        )

    executed = []
    for call in hybrid_result.get("function_calls", []):
        tool_result = execute_tool(call["name"], call["arguments"])
        executed.append({
            "name": call["name"],
            "arguments": call["arguments"],
            "result": tool_result,
        })

    return {
        "transcription": transcribe_text,
        "transcribe_latency_ms": round(transcribe_ms, 1),
        "function_calls": executed,
        "source": hybrid_result.get("source", "unknown"),
        "routing_latency_ms": round(hybrid_result.get("total_time_ms", routing_ms), 1),
    }


@app.on_event("startup")
async def startup_preload():
    """Pre-load Whisper model in background thread at startup."""
    import threading
    def _load():
        print("[INFO] Pre-loading Whisper model...")
        w = _get_whisper()
        if w:
            print("[INFO] Whisper model loaded successfully")
        else:
            print("[WARN] Whisper model failed to load")
    threading.Thread(target=_load, daemon=True).start()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
