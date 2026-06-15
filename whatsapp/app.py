from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from openai import OpenAI
import os
import json
from datetime import datetime

app = Flask(__name__)
client = OpenAI()

STATE_FILE = os.path.join(os.path.dirname(__file__), "conversation_state.json")

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
Do not invent facts, policies, fees, availability, exact addresses, listing features, or roommate details.
If the knowledge base conflicts with older instructions, follow the knowledge base.

TONE
- Human, direct, calm, and helpful.
- Conversational, like a leasing agent texting on WhatsApp.
- Confident, but not pushy or fake-excited.
- Avoid robotic openings like “Absolutely!”, “Great question!”, “I appreciate your question!”, “I totally understand your concern!” unless it truly fits.
- Avoid excessive enthusiasm, emojis, exclamation points, and filler.

RESPONSE LENGTH
Default to short answers:
- 2 to 5 short sentences for normal questions.
- Use bullets only when explaining a process, payment breakdown, or multiple steps.
- Do not write long paragraphs.
- Do not repeat the lead’s question back unless needed for clarity.
- Do not over-explain policies unless the lead asks for detail.

RESPONSE STRUCTURE
Use this structure when possible:
1. Brief acknowledgement only if natural.
2. Direct answer first.
3. Add the key condition/rule.
4. Give the next step or ask one useful follow-up question.

For high-intent leads, prioritize action:
- application link
- listing number
- move-in date
- payment timing
- showing/video-call link if needed

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
- If the lead is early-stage, ask for move-in date, length of stay, budget, and preferred area.
- If the lead has found a room and sounds interested, guide them toward applying.
- If the lead is ready to book, explain the exact sequence: application → approval → lease → invoice → payment → secured.
- Remind leads that rooms are first come, first served and not secured until required payment is completed.
- Do not pressure someone into skipping necessary information, but do not be passive when they are ready.

FACTUAL SAFETY
- Do not confirm live availability unless it has been verified.
- Do not confirm exact current pricing unless the lead provided it or it is in confirmed listing data.
- Do not give exact unit addresses during sales conversations.
- Do not provide security/access details.
- Do not promise approval.
- Do not say a room is secured before lease/payment requirements are completed.

ESCALATION
If the answer requires live availability, exact current pricing, billing/account review, legal interpretation, lease exception, exact address, special approval, or anything not covered in the knowledge base, give the best safe partial answer and add:
[ESCALATE]

Do not overuse [ESCALATE]. Use it only when a human really should review.

STYLE EXAMPLES
Bad:
“Absolutely! I totally understand your concern 😊”

Better:
“Good question. Here’s how that works.”

Bad:
“[Application Link](https://...)”

Better:
“You can apply here: https://easylivingspacesllc.managebuilding.com/Resident/rental-application/new”

Bad:
“Typically, rooms may have locks.”

Better:
“Yes, every individual room has its own lock for privacy.”
"""

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

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


@app.route("/whatsapp", methods=["POST"])
def whatsapp_reply():
    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From", "")

    print(f"Message from {sender}: {incoming_msg}")

    state = load_state()
    convo = state.get(sender, {"messages": []})

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

    state[sender] = convo
    save_state(state)

    resp = MessagingResponse()
    msg = resp.message()
    msg.body(reply_text)
    return str(resp)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)