import streamlit as st
import pandas as pd
import numpy as np
import re
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="Student Focus AI Chatbot",
    page_icon="🎓",
    layout="centered"
)

# ============================================================
# TITLE
# ============================================================

st.title("🎓 Student Focus AI Chatbot")
st.caption("AI-powered study pattern analysis and personalized recommendations")

# ============================================================
# GENERATE TRAINING DATA
# ============================================================

@st.cache_data
def generate_data():

    np.random.seed(42)

    subjects = [
        "Python",
        "Artificial Intelligence",
        "Machine Learning",
        "DBMS",
        "Mathematics",
        "Data Structures"
    ]

    rows = []

    for i in range(1000):

        subject = np.random.choice(subjects)

        study_duration = np.random.randint(20, 121)

        break_duration = np.random.randint(5, 31)

        study_hour = np.random.randint(6, 24)

        distractions = np.random.randint(0, 11)

        sleep_hours = round(
            np.random.uniform(4.5, 9),
            1
        )

        previous_score = np.random.randint(40, 101)

        # Calculate synthetic focus pattern
        score = 0

        score += min(study_duration / 30, 4)

        score += sleep_hours * 0.35

        score += previous_score * 0.025

        score -= distractions * 0.35

        if 17 <= study_hour <= 21:
            score += 1.5

        if study_duration > 100:
            score -= 0.8

        score += np.random.normal(0, 1)

        focus_level = int(
            np.clip(
                round(score / 2),
                1,
                5
            )
        )

        rows.append([
            subject,
            study_duration,
            break_duration,
            study_hour,
            distractions,
            sleep_hours,
            previous_score,
            focus_level
        ])

    columns = [
        "subject",
        "study_duration",
        "break_duration",
        "study_hour",
        "distractions",
        "sleep_hours",
        "previous_score",
        "focus_level"
    ]

    return pd.DataFrame(
        rows,
        columns=columns
    )


data = generate_data()

# ============================================================
# TRAIN RANDOM FOREST MODEL
# ============================================================

features = [
    "study_duration",
    "break_duration",
    "study_hour",
    "distractions",
    "sleep_hours",
    "previous_score"
]

X = data[features]

y = data["focus_level"]

X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.20,
    random_state=42,
    stratify=y
)

model = RandomForestClassifier(
    n_estimators=150,
    random_state=42
)

model.fit(
    X_train,
    y_train
)

predictions = model.predict(X_test)

accuracy = accuracy_score(
    y_test,
    predictions
)

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def focus_name(level):

    names = {
        1: "Very Low",
        2: "Low",
        3: "Moderate",
        4: "High",
        5: "Very High"
    }

    return names.get(
        int(level),
        "Unknown"
    )


def extract_number(text, keywords, default=None):

    for keyword in keywords:

        pattern = rf"{keyword}\s*(?:is|of|:)?\s*(\d+(?:\.\d+)?)"

        match = re.search(
            pattern,
            text.lower()
        )

        if match:
            return float(match.group(1))

    return default


def extract_study_data(message):

    text = message.lower()

    # Study duration
    duration = None

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)",
        text
    )

    if match:

        duration = float(match.group(1)) * 60

    else:

        match = re.search(
            r"(\d+)\s*(?:minutes?|mins?)",
            text
        )

        if match:
            duration = float(
                match.group(1)
            )

    # Break
    break_time = extract_number(
        text,
        [
            r"break",
            r"break time"
        ],
        10
    )

    # Distractions
    distractions = extract_number(
        text,
        [
            r"distractions?",
            r"distraction"
        ],
        2
    )

    # Sleep
    sleep = extract_number(
        text,
        [
            r"sleep",
            r"slept"
        ],
        7
    )

    # Previous score
    score = extract_number(
        text,
        [
            r"score",
            r"marks",
            r"previous score"
        ],
        75
    )

    # Study hour
    hour = None

    time_match = re.search(
        r"(\d{1,2})\s*(am|pm)",
        text
    )

    if time_match:

        hour = int(
            time_match.group(1)
        )

        period = time_match.group(2)

        if period == "pm" and hour != 12:
            hour += 12

        if period == "am" and hour == 12:
            hour = 0

    if hour is None:
        hour = 19

    return {
        "duration": duration,
        "break_time": break_time,
        "hour": hour,
        "distractions": distractions,
        "sleep": sleep,
        "score": score
    }


def predict_focus(info):

    duration = info["duration"]

    if duration is None:
        duration = 60

    input_data = pd.DataFrame(
        [[
            duration,
            info["break_time"],
            info["hour"],
            info["distractions"],
            info["sleep"],
            info["score"]
        ]],
        columns=features
    )

    prediction = int(
        model.predict(input_data)[0]
    )

    confidence = (
        model.predict_proba(input_data).max()
        * 100
    )

    return prediction, confidence


def generate_response(message):

    text = message.lower()

    # Greeting
    if any(word in text for word in [
        "hello",
        "hi",
        "hey"
    ]):

        return (
            "👋 Hello! I'm your **Student Focus AI Assistant**.\n\n"
            "Tell me about your study session and I can analyze "
            "your focus pattern.\n\n"
            "For example:\n"
            "> I studied Python for 60 minutes at 7 pm "
            "with 2 distractions and slept 7 hours."
        )

    # Help
    if "help" in text or "what can you do" in text:

        return (
            "🤖 I can help you with:\n\n"
            "• 🎯 Predict your focus level\n"
            "• 📊 Analyze your study pattern\n"
            "• 🕐 Identify productive study times\n"
            "• 📱 Analyze distractions\n"
            "• 📚 Give subject-study recommendations\n"
            "• 📅 Suggest a study strategy\n\n"
            "Just describe your study session."
        )

    # Study time
    if (
        "best time" in text
        or "study time" in text
        or "when should i study" in text
    ):

        hourly = (
            data.groupby("study_hour")["focus_level"]
            .mean()
        )

        best_hour = int(
            hourly.idxmax()
        )

        return (
            f"🕐 Based on the available study-pattern data, "
            f"the strongest recorded study period is around "
            f"**{best_hour}:00**.\n\n"
            "You can compare your own sessions over time "
            "to see whether this pattern matches your experience."
        )

    # Subject priority
    if (
        "subject" in text
        and (
            "priority" in text
            or "which subject" in text
            or "need" in text
        )
    ):

        grouped = data.groupby("subject").agg(
            avg_score=("previous_score", "mean"),
            avg_focus=("focus_level", "mean")
        )

        grouped["priority"] = (
            (100 - grouped["avg_score"]) * 0.5
            + (5 - grouped["avg_focus"]) * 10
        )

        subject = grouped["priority"].idxmax()

        return (
            f"📚 Based on the sample study data, "
            f"**{subject}** has the highest calculated "
            f"attention priority.\n\n"
            "This priority is calculated from recorded score "
            "and focus patterns."
        )

    # Distraction question
    if "distraction" in text:

        info = extract_study_data(message)

        distractions = info["distractions"]

        if distractions >= 5:

            return (
                f"📱 You reported about **{int(distractions)} "
                "distractions**.\n\n"
                "That's a relatively high distraction count "
                "for this prediction. Try reducing notifications "
                "and keeping your phone away during focused study."
            )

        elif distractions >= 3:

            return (
                f"📱 You reported about **{int(distractions)} "
                "distractions**.\n\n"
                "Try reducing unnecessary notifications and "
                "interruptions."
            )

        else:

            return (
                f"✅ You reported about **{int(distractions)} "
                "distractions**.\n\n"
                "Your reported distraction level is relatively low."
            )

    # If message contains study information
    info = extract_study_data(message)

    has_study_data = (
        info["duration"] is not None
        or "studied" in text
        or "study" in text
        or "focus" in text
        or "concentrate" in text
    )

    if has_study_data:

        prediction, confidence = predict_focus(info)

        response = (
            "📊 **Study Pattern Analysis**\n\n"
            f"🎯 Predicted Focus: **{prediction}/5**\n\n"
            f"📌 Focus Category: **{focus_name(prediction)}**\n\n"
            f"🤖 Model Confidence: **{confidence:.1f}%**\n\n"
            "💡 **Recommendations:**\n"
        )

        for item in make_recommendations(
            prediction,
            info["distractions"],
            info["sleep"],
            info["duration"] or 60,
            info["hour"]
        ):

            response += f"\n{item}"

        return response

    # Default response
    return (
        "🤔 I didn't get enough study information.\n\n"
        "Try saying something like:\n\n"
        "**I studied Python for 60 minutes at 7 pm, "
        "had 2 distractions, slept 7 hours and scored 80.**"
    )


# ============================================================
# CHATBOT RECOMMENDATIONS
# ============================================================

def make_recommendations(
    focus,
    distractions,
    sleep,
    duration,
    hour
):

    result = []

    if focus <= 2:

        result.append(
            "🔴 Your predicted focus is low. "
            "Try shorter 25–30 minute study sessions."
        )

    elif focus == 3:

        result.append(
            "🟡 Your focus is moderate. "
            "Try 40–50 minute focused sessions."
        )

    else:

        result.append(
            "🟢 Your focus pattern is strong. "
            "Continue your current routine."
        )

    if distractions >= 5:

        result.append(
            "📵 Distractions are high. "
            "Try keeping your phone away while studying."
        )

    elif distractions >= 3:

        result.append(
            "📱 Try reducing notifications and unnecessary "
            "screen activity."
        )

    if sleep < 6:

        result.append(
            "😴 Your recorded sleep duration is low. "
            "A consistent sleep schedule may help your study routine."
        )

    if duration > 100:

        result.append(
            "⏱️ This is a long study session. "
            "Consider taking a short break."
        )

    if 17 <= hour <= 21:

        result.append(
            "⭐ This study time falls within the stronger "
            "study period identified in the sample data."
        )

    return result


# ============================================================
# CHAT INTERFACE
# ============================================================

if "messages" not in st.session_state:

    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                "👋 **Hello! I'm your Student Focus AI Assistant.**\n\n"
                "Tell me about your study session and I'll analyze "
                "your focus pattern.\n\n"
                "Example:\n\n"
                "💬 *I studied Python for 60 minutes at 7 pm "
                "with 2 distractions and slept 7 hours.*"
            )
        }
    ]


for message in st.session_state.messages:

    with st.chat_message(
        message["role"]
    ):

        st.markdown(
            message["content"]
        )


user_message = st.chat_input(
    "Tell me about your study session..."
)


if user_message:

    st.session_state.messages.append(
        {
            "role": "user",
            "content": user_message
        }
    )

    with st.chat_message("user"):
        st.markdown(user_message)

    response = generate_response(
        user_message
    )

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": response
        }
    )

    with st.chat_message("assistant"):
        st.markdown(response)


# ============================================================
# SIDEBAR INFORMATION
# ============================================================

with st.sidebar:

    st.title("🎓 Student Focus AI")

    st.markdown("---")

    st.subheader("🤖 AI Model")

    st.write(
        "Random Forest Classifier"
    )

    st.write(
        f"Training Samples: {len(X_train)}"
    )

    st.write(
        f"Testing Samples: {len(X_test)}"
    )

    st.write(
        f"Test Accuracy: {accuracy * 100:.2f}%"
    )

    st.markdown("---")

    st.subheader("💬 Example Questions")

    st.write(
        "• How focused am I?"
    )

    st.write(
        "• When should I study?"
    )

    st.write(
        "• I get distracted a lot"
    )

    st.write(
        "• Which subject needs attention?"
    )

    st.write(
        "• I studied Python for 90 minutes"
    )

    st.markdown("---")

    if st.button("🗑️ Clear Chat"):

        st.session_state.messages = []

        st.rerun()

st.caption(
    "AI-Based Student Focus Pattern Analyzer | "
    "Python + Machine Learning + Streamlit"
)
