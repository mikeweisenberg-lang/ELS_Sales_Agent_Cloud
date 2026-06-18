from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from openai import OpenAI
import os
import json
from datetime import datetime
from supabase import create_client

app = Flask(__name__)
client = OpenAI()

STATE_FILE = os.path.join(os.path.dirname(__file__), "conversation_state.json")  # local fallback only

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY) if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY else None
print(f"Supabase memory configured: {bool(supabase)}")

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
KNOWLEDGE_FILE = os.path.join(BASE_DIR, "knowledge_base", "sales_agent_knowledge.md")

def load_sales_knowledge():
    try:
        with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"Knowledge base load error: {e}")
        return "Knowledge base could not be loaded. Use only general approved Easy Living Spaces rules and mark uncertain answers with [ESCALATE]."

APPLICATION_LINK = "https://easylivingspacesllc.managebuilding.com/Resident/rental-application/new"
SHOWING_LINK = "https://calendly.com/propertymanager-easylivingspaces/30min"
WEBSITE = "https://www.easylivingspaces.com"

SYSTEM_PROMPT = """
You are the WhatsApp sales agent for Easy Living Spaces.

Your job is to act like a real leasing specialist texting with a prospective renter.

PRIMARY GOAL
Help qualified leads understand Easy Living Spaces and move them toward the right next step:
- choose a listing
- submit an application
- schedule a showing/video call when needed
- escalate when a human should review

SOURCE OF TRUTH
Use the Easy Living Spaces knowledge base provided in the user input as the main source of truth.
Do not invent facts, policies, fees, availability, exact addresses, listing features, roommate details, pricing, or listing amenities.
If the knowledge base conflicts with older instructions, follow the knowledge base.

CURRENT STYLE TARGET
The target voice is:
Warm, concise, conversational leasing agent.

Do not sound like:
- a robot
- a customer support script
- an overly excited social media assistant
- a cold transactional responder
- an essay writer

TONE
- Human, direct, calm, helpful, and lightly warm.
- Conversational, like a real leasing agent texting on WhatsApp.
- Confident, but not pushy or fake-excited.
- Avoid robotic openings like “Absolutely!”, “Great question!”, “I appreciate your question!”, “I totally understand your concern!”, or “I’m thrilled...” unless it truly fits.
- Avoid emojis, excessive exclamation points, and filler.
- Do not over-apologize or over-validate.
- A simple “Good question.” is acceptable sometimes, but not every time.
- In the middle of an ongoing conversation, usually skip the greeting and answer directly.

OPENING / FIRST MESSAGE BEHAVIOR
When a new lead first texts with a basic inquiry, be warm but not repetitive.
Do not repeat their whole message back to them.
A good first-message pattern is:
“Hi there, thank you for your interest in Easy Living Spaces. We can definitely help. The best next step is to check availability on our website using your preferred move-in date: https://www.easylivingspaces.com”

If more information is needed, ask one useful follow-up question, not several unless necessary.

RESPONSE LENGTH
Default to short answers:
- 2 to 5 short sentences for normal questions.
- Use bullets only when explaining a process, payment breakdown, or multiple steps.
- Do not write long paragraphs.
- Do not repeat the lead’s question back unless needed for clarity.
- Do not over-explain policies unless the lead asks for detail.
- When the user asks multiple questions, answer each clearly but still keep it tight.

RESPONSE STRUCTURE
Use this structure when possible:
1. Direct answer first.
2. Add the key rule/condition.
3. Give the next step or ask one useful follow-up question.

For high-intent leads, prioritize action:
- application link
- listing number
- move-in date
- payment timing
- showing/video-call link if needed

Do not add generic closing questions like “Would you like me to help you with anything else?” after every answer.
Only ask a follow-up question if it meaningfully moves the lead forward.

WHATSAPP FORMATTING RULES
- Do not use markdown links like [Application Link](https://...).
- Paste full plain URLs.
- Do not use markdown bold formatting with **.
- Avoid emojis unless the user’s tone clearly invites it.
- Keep formatting simple and WhatsApp-safe.
- Never send an empty reply.

IMPORTANT LINKS
Website: https://www.easylivingspaces.com
Application: https://easylivingspacesllc.managebuilding.com/Resident/rental-application/new
Showing: https://calendly.com/propertymanager-easylivingspaces/30min
Video call: https://calendly.com/easylivingspaces/video-call-with-easy-living-spaces

SALES BEHAVIOR
- If the lead is early-stage and has not provided basics, ask for move-in date, length of stay, budget, and preferred area.
- If the lead already gave move-in and move-out dates, do not ask for those again.
- If the lead has found a room and sounds interested, guide them toward applying.
- If the lead is ready to book, explain the exact sequence: application → approval → lease → invoice → payment → secured.
- The application must happen before lease/invoice/payment.
- Remind leads that rooms are first come, first served and not secured until the required payment is completed.
- Do not pressure someone into skipping necessary information, but do not be passive when they are ready.

FACTUAL SAFETY
- Do not confirm live availability unless it has been verified.
- Do not confirm exact current pricing unless the lead provided it or it is in confirmed listing data.
- If the user provides a price/listing and asks what is included, answer based on that given price without saying “typically.”
- Do not use soft language like “typically” when the policy is definite.
- Do not give exact unit addresses during sales conversations.
- Do not provide security/access details.
- Do not promise approval.
- Do not say a room is secured before lease/payment requirements are completed.

ESCALATION
If the answer requires live availability, exact current pricing not supplied by the lead/listing data, billing/account review, legal interpretation, lease exception, exact address, special approval, or anything not covered in the knowledge base, give the best safe partial answer and add:
[ESCALATE]

Do not overuse [ESCALATE]. Use it only when a human really should review.

STYLE EXAMPLES
Bad:
“Absolutely! I totally understand your concern 😊”

Better:
“Good question. Here’s how that works.”

Bad:
“Great question! 🔑 Typically, the individual rooms do come with locks...”

Better:
“Yes, every individual room comes with its own lock for privacy.”

Bad:
“[Application Link](https://...)”

Better:
“You can apply here: https://easylivingspacesllc.managebuilding.com/Resident/rental-application/new”

Bad:
“Can you provide your move-in and move-out dates?” when the lead already gave them.

Better:
“Thanks for sharing your dates. For September through December, the best next step is to check current availability here: https://www.easylivingspaces.com”
"""

def load_state():
    # Local fallback only. Production memory should use Supabase.
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(state):
    # Local fallback only. Production memory should use Supabase.
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

def load_conversation(sender):
    if supabase:
        try:
            result = (
                supabase.table("sales_agent_conversations")
                .select("messages")
                .eq("sender", sender)
                .limit(1)
                .execute()
            )
            if result.data:
                messages = result.data[0].get("messages") or []
                return {"messages": messages}
            return {"messages": []}
        except Exception as e:
            print(f"Supabase load error: {e}")

    state = load_state()
    return state.get(sender, {"messages": []})

def get_memory_limit() -> int:
    """Read memory limit safely so a bad env var never crashes the bot."""
    raw = os.getenv("ELS_MEMORY_MAX_MESSAGES", "40")
    try:
        value = int(raw)
    except Exception:
        print(f"Invalid ELS_MEMORY_MAX_MESSAGES={raw!r}; using 40")
        return 40
    return max(8, min(value, 100))

def save_conversation(sender, convo):
    messages = convo.get("messages", [])

    # Keep database rows compact. This still gives the agent recent context,
    # while preserving enough conversation history for useful continuity.
    max_saved_messages = get_memory_limit()
    if len(messages) > max_saved_messages:
        messages = messages[-max_saved_messages:]
        convo["messages"] = messages

    if supabase:
        try:
            now = datetime.utcnow().isoformat()
            payload = {
                "sender": sender,
                "messages": messages,
                "last_message_at": now,
                "updated_at": now,
            }
            supabase.table("sales_agent_conversations").upsert(payload, on_conflict="sender").execute()
            print(f"Supabase memory saved for {sender}; messages={len(messages)}")
            return
        except Exception as e:
            print(f"Supabase save error: {e}")

    # Local fallback only if Supabase is not configured or temporarily fails.
    # This prevents the bot from going down, but production memory should be Supabase.
    state = load_state()
    state[sender] = convo
    save_state(state)
    print(f"Local fallback memory saved for {sender}; messages={len(messages)}")

def build_history_text(messages):
    recent = messages[-8:]
    return "\n".join([f"{m['role']}: {m['content']}" for m in recent])

def clean_whatsapp_reply(text):
    text = (text or "").strip()

    replacements = {
        "[Application Link](https://easylivingspacesllc.managebuilding.com/Resident/rental-application/new)": "Application link: https://easylivingspacesllc.managebuilding.com/Resident/rental-application/new",
        "[Showing Link](https://calendly.com/propertymanager-easylivingspaces/30min)": "Showing link: https://calendly.com/propertymanager-easylivingspaces/30min",
        "[Video Call Link](https://calendly.com/easylivingspaces/video-call-with-easy-living-spaces)": "Video call link: https://calendly.com/easylivingspaces/video-call-with-easy-living-spaces",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    # Remove common markdown formatting that can behave poorly in WhatsApp.
    text = text.replace("**", "")
    text = text.replace("__", "")

    # Remove excessive blank lines.
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")

    return text.strip()


@app.route("/", methods=["GET"])
def home():
    return "ELS Sales Agent is running", 200

@app.route("/health", methods=["GET"])
def health():
    return {
        "status": "ok",
        "supabase_configured": bool(supabase),
        "memory_max_messages": get_memory_limit(),
    }, 200

@app.route("/whatsapp", methods=["POST"])
def whatsapp_reply():
    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From", "")

    print(f"Message from {sender}: {incoming_msg}")

    if not incoming_msg:
        resp = MessagingResponse()
        resp.message().body("Thanks for reaching out to Easy Living Spaces. How can I help?")
        return str(resp)

    convo = load_conversation(sender)

    convo["messages"].append({
        "role": "lead",
        "content": incoming_msg,
        "time": datetime.now().isoformat()
    })

    history_text = build_history_text(convo["messages"])
    sales_knowledge = load_sales_knowledge()
    
    user_input = f"""
Use the following Easy Living Spaces knowledge base as the main source of truth.

SALES AGENT KNOWLEDGE BASE:
{sales_knowledge}

Conversation so far:
{history_text}

Latest lead message:
{incoming_msg}

Write the next WhatsApp reply as the Easy Living Spaces sales agent.
Follow the knowledge base rules, approved answer patterns, escalation rules, and response examples.
Keep the reply short, direct, and WhatsApp-safe.
Do not use markdown links. Use plain URLs only.
If the answer requires information not available in the knowledge base, give a helpful partial answer and include [ESCALATE].
"""
    try:
        response = client.responses.create(
            model=os.getenv("ELS_SALES_AGENT_MODEL", "gpt-4o-mini"),
            instructions=SYSTEM_PROMPT,
            input=user_input,
        )
        reply_text = response.output_text.strip()
        reply_text = clean_whatsapp_reply(reply_text)
        print(f"Bot reply: {reply_text}")

        if not reply_text:
            reply_text = "Thanks — I understand. I’m going to have our team review this and follow up with you directly. [ESCALATE]"

    except Exception as e:
        print(f"OpenAI error: {e}")
        reply_text = "Thanks for reaching out to Easy Living Spaces. I’m having trouble checking that right now, but I’ll have a team member follow up. [ESCALATE]"

    convo["messages"].append({
        "role": "agent",
        "content": reply_text,
        "time": datetime.now().isoformat()
    })

    save_conversation(sender, convo)

    resp = MessagingResponse()
    msg = resp.message()
    msg.body(reply_text)
    return str(resp)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
