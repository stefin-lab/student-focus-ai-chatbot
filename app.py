import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import re
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

st.set_page_config(page_title="Student Focus AI Chatbot", page_icon="🎓", layout="wide")

@st.cache_data
def make_data():
    np.random.seed(42)
    subjects=["Python","Artificial Intelligence","Machine Learning","DBMS","Mathematics","Data Structures"]
    rows=[]
    for i in range(1000):
        subject=np.random.choice(subjects); duration=np.random.randint(20,121); br=np.random.randint(5,31)
        hour=np.random.randint(6,24); dis=np.random.randint(0,11); sleep=round(np.random.uniform(4.5,9),1); prev=np.random.randint(40,101)
        s=min(duration/30,4)+sleep*.35+prev*.025-dis*.35+(1.5 if 17<=hour<=21 else 0)-(0.8 if duration>100 else 0)+np.random.normal(0,1)
        focus=int(np.clip(round(s/2),1,5)); rows.append([i+1,subject,duration,br,hour,dis,sleep,prev,focus])
    return pd.DataFrame(rows,columns=["student_id","subject","study_duration","break_duration","study_hour","distractions","sleep_hours","previous_score","focus_level"])

data=make_data()
FEATURES=["study_duration","break_duration","study_hour","distractions","sleep_hours","previous_score"]
X=data[FEATURES]; y=data.focus_level
Xtr,Xte,ytr,yte=train_test_split(X,y,test_size=.2,random_state=42)
@st.cache_resource
def get_model(a,b):
    m=RandomForestClassifier(n_estimators=150,random_state=42); m.fit(a,b); return m
model=get_model(Xtr,ytr); accuracy=accuracy_score(yte,model.predict(Xte))

if "chat" not in st.session_state: st.session_state.chat=[]
if "history" not in st.session_state: st.session_state.history=[]

def level(n): return {1:"Very Low",2:"Low",3:"Moderate",4:"High",5:"Very High"}.get(int(n),"Unknown")
def score(n): return int(round(int(n)*20))
def best_time(df):
    h=int(df.groupby("study_hour").focus_level.mean().idxmax()); return f"{h if 1<=h<=12 else (h-12 if h>12 else 12)}:00 {'AM' if h<12 else 'PM'}"
def recs(f,d,s,t,h):
    r=[]
    r.append("🔴 Focus is low. Try 25–30 minute focused sessions." if f<=2 else "🟡 Focus is moderate. Try 40–50 minute sessions." if f==3 else "🟢 Focus is strong. Continue your current routine.")
    r.append("📵 Distractions are high. Keep your phone away." if d>=5 else "📱 Reduce notifications and unnecessary screen activity." if d>=3 else "✅ Distraction level is under control.")
    r.append("😴 Sleep is low. Aim for a consistent sleep routine." if s<6 else "🌙 Try to increase sleep toward 7–8 hours." if s<7 else "😴 Sleep duration is in a good range.")
    if t>100:r.append("⏱️ Session is long. Take a short break before continuing.")
    if 17<=h<=21:r.append("⭐ This is within the stronger study period found in the training data.")
    return r

def parse(text):
    x=text.lower()
    def num(patterns,default=None,typ=float):
        for p in patterns:
            m=re.search(p,x,re.I)
            if m:
                try:return typ(m.group(1))
                except:pass
        return default
    duration=num([r"(\d+(?:\.\d+)?)\s*(?:minutes?|mins?|min)\s*(?:of\s*)?(?:study|studied|studying)?",r"(?:study|studied|studying)\s*(?:for\s*)?(\d+(?:\.\d+)?)\s*(?:minutes?|mins?|min)"],None)
    h=None
    m=re.search(r"(?:at|around)\s*(\d{1,2})(?::\d{2})?\s*(am|pm)?",x)
    if m:
        h=int(m.group(1)); ap=m.group(2)
        if ap=="pm" and h<12:h+=12
        if ap=="am" and h==12:h=0
    dis=num([r"(\d+)\s*distractions?"],None,int)
    sleep=num([r"(?:slept|sleep|sleeping)\s*(?:for\s*)?(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)"],None)
    prev=num([r"(?:previous|last|score|mark|marks)\s*(?:score|mark|marks)?\s*(?:was|is|of)?\s*(\d+(?:\.\d+)?)\s*(?:%|percent)?"],75)
    subs=["python","artificial intelligence","machine learning","dbms","mathematics","data structures"]
    subject=next((s.title() for s in subs if s in x),"General Study")
    if duration is not None and h is not None and dis is not None and sleep is not None:
        return dict(duration=float(duration),break_duration=10.,hour=max(0,min(23,h)),distractions=int(dis),sleep=float(sleep),previous_score=max(0,min(100,float(prev))),subject=subject)

def analyze(s,save=True):
    inp=pd.DataFrame([[s["duration"],s["break_duration"],s["hour"],s["distractions"],s["sleep"],s["previous_score"]]],columns=FEATURES)
    p=int(model.predict(inp)[0]); conf=float(model.predict_proba(inp).max()*100); s=dict(s,focus_level=p,focus_score=score(p),confidence=conf)
    if save: st.session_state.history.append(s)
    return s

def bot(text):
    p=parse(text)
    if p:
        r=analyze(p)
        out=f"### 🎯 Study Session Analysis\n\n**Subject:** {r['subject']}  \n**Focus Score:** **{r['focus_score']}/100**  \n**Focus Level:** **{level(r['focus_level'])}**  \n**Model Confidence:** **{r['confidence']:.1f}%**\n\n### 💡 Recommendations\n"
        return out+"\n".join("- "+x for x in recs(r['focus_level'],r['distractions'],r['sleep'],r['duration'],r['hour']))+"\n\n📌 Session added to Study History."
    x=text.lower()
    if any(w in x for w in ["hello","hi","hey"]): return "👋 Hello! I'm your Student Focus AI Assistant. Tell me about your study session or ask about study time, distractions, subjects, or planning."
    if "best study" in x or "productive" in x or "study time" in x:return f"⭐ A strong study period in the training data is around **{best_time(data)}**."
    if "distract" in x or "phone" in x:return "📵 Keep your phone away, disable unnecessary notifications, use 25–50 minute focus blocks, and take planned breaks."
    if "subject" in x or "priority" in x:
        q=priority(data).iloc[0]; return f"📚 Current priority suggestion: **{q.subject}**\n\nAverage score: **{q.avg_score:.1f}%**  \nAverage focus: **{q.avg_focus:.1f}/5**"
    if "help" in x or "what can" in x:return "🤖 I can predict focus, give recommendations, find a study time, analyze distractions, prioritize subjects, create study plans, track history, and generate a daily report."
    return "💬 Try: **I studied Python for 60 minutes at 7 pm with 2 distractions and slept 7 hours.**"

def priority(df):
    q=df.groupby("subject").agg(avg_score=("previous_score","mean"),avg_focus=("focus_level","mean"),study_time=("study_duration","mean")).reset_index()
    q["priority_score"]=(100-q.avg_score)*.55+(5-q.avg_focus)*10
    return q.sort_values("priority_score",ascending=False)

st.sidebar.title("🎓 Student Focus AI")
menu=st.sidebar.radio("Navigate",["🤖 AI Chatbot","🔮 Focus Prediction","📈 Study Analytics","📚 Subject Priority","📅 Study Planner","📋 Study History","📄 Daily Report","📥 Download Data"])
st.sidebar.markdown("---")
st.sidebar.write("**Algorithm:** Random Forest Classifier")
st.sidebar.write(f"**Training Samples:** {len(Xtr)}")
st.sidebar.write(f"**Testing Samples:** {len(Xte)}")
st.sidebar.write(f"**Test Accuracy:** {accuracy*100:.2f}%")
if st.sidebar.button("🗑️ Clear Study History"): st.session_state.history=[]; st.rerun()

if menu=="🤖 AI Chatbot":
    st.title("🎓 Student Focus AI Chatbot"); st.caption("AI-powered study pattern analysis and personalized recommendations")
    if not st.session_state.chat: st.info("👋 Hello! Example: **I studied Python for 60 minutes at 7 pm with 2 distractions and slept 7 hours.**")
    for role,msg in st.session_state.chat:
        with st.chat_message(role):st.markdown(msg)
    prompt=st.chat_input("Tell me about your study session...")
    if prompt:
        st.session_state.chat.append(("user",prompt)); st.session_state.chat.append(("assistant",bot(prompt))); st.rerun()

elif menu=="🔮 Focus Prediction":
    st.header("🔮 AI Focus Prediction")
    a,b=st.columns(2)
    with a: dur=st.number_input("Study Duration (minutes)",5,300,60); br=st.number_input("Break Duration (minutes)",0,120,10); hr=st.slider("Study Hour",0,23,19)
    with b: dis=st.slider("Expected Distractions",0,20,2); sl=st.slider("Sleep Hours",1.,12.,7.,.5); ps=st.slider("Previous Score",0,100,75)
    if st.button("🔮 Predict Focus",type="primary"):
        r=analyze(dict(duration=float(dur),break_duration=float(br),hour=int(hr),distractions=int(dis),sleep=float(sl),previous_score=float(ps),subject="Manual Prediction"),save=False)
        c1,c2,c3=st.columns(3); c1.metric("Focus Score",f"{r['focus_score']}/100"); c2.metric("Focus Level",level(r['focus_level'])); c3.metric("Confidence",f"{r['confidence']:.1f}%"); st.progress(r['focus_score']/100)
        st.subheader("💡 Recommendations"); [st.write(x) for x in recs(r['focus_level'],dis,sl,dur,hr)]

elif menu=="📈 Study Analytics":
    st.header("📈 Study & Focus Analytics")
    c1,c2,c3,c4=st.columns(4); c1.metric("Average Focus",f"{data.focus_level.mean():.2f}/5"); c2.metric("Average Study Time",f"{data.study_duration.mean():.1f} min"); c3.metric("Average Distractions",f"{data.distractions.mean():.1f}"); c4.metric("Average Sleep",f"{data.sleep_hours.mean():.1f} hrs")
    q=data.focus_level.value_counts().sort_index().reset_index(); q.columns=["Focus Level","Count"]; st.plotly_chart(px.bar(q,x="Focus Level",y="Count",title="Focus Level Distribution"),use_container_width=True)
    c1,c2=st.columns(2)
    with c1:
        h=data.groupby("study_hour").focus_level.mean().reset_index(); st.plotly_chart(px.line(h,x="study_hour",y="focus_level",markers=True,title="Average Focus by Study Time"),use_container_width=True)
    with c2: st.plotly_chart(px.scatter(data,x="distractions",y="focus_level",color="subject",title="Distractions vs Focus"),use_container_width=True)
    st.plotly_chart(px.scatter(data,x="sleep_hours",y="focus_level",color="subject",title="Sleep Duration vs Focus"),use_container_width=True)
    st.success(f"⭐ Best study time from training data: **{best_time(data)}**")

elif menu=="📚 Subject Priority":
    st.header("📚 Subject Priority Analysis"); q=priority(data); st.dataframe(q.rename(columns={"subject":"Subject","avg_score":"Average Score","avg_focus":"Average Focus","study_time":"Average Study Time","priority_score":"Priority Score"}),use_container_width=True); st.plotly_chart(px.bar(q,x="subject",y="priority_score",title="Subject Priority"),use_container_width=True)

elif menu=="📅 Study Planner":
    st.header("📅 Personalized Study Plan"); hours=st.slider("Available Study Time (hours)",1.,8.,3.,.5); text=st.text_input("Subjects","Python, Mathematics"); subs=[x.strip() for x in text.split(",") if x.strip()]
    if st.button("✨ Generate Study Plan",type="primary"):
        total=int(hours*60); rows=[]
        for i,s in enumerate(subs): rows.append({"Order":i+1,"Subject":s,"Focus Time":f"{max(20,total//len(subs))} min","Break":"10 min" if i<len(subs)-1 else "Final review"})
        st.dataframe(pd.DataFrame(rows),use_container_width=True); st.success("🎯 Put your most difficult subject in your strongest study period.")

elif menu=="📋 Study History":
    st.header("📋 Your Study History")
    if not st.session_state.history: st.info("No sessions yet. Use the chatbot with a complete study-session message.")
    else:
        q=pd.DataFrame(st.session_state.history); q["Focus"]=q.focus_level.apply(level); st.dataframe(q[["subject","duration","hour","distractions","sleep","previous_score","focus_score","Focus"]],use_container_width=True); st.plotly_chart(px.line(q.reset_index(),x="index",y="focus_score",markers=True,title="Focus Score Progress"),use_container_width=True)
        if len(q)>=2:
            d=q.focus_score.iloc[-1]-q.focus_score.iloc[0]; st.success(f"📈 Focus improved by {d} points.") if d>0 else st.warning(f"📉 Focus is {abs(d)} points lower than the first session.") if d<0 else st.info("➡️ Focus is unchanged from the first session.")

elif menu=="📄 Daily Report":
    st.header("📄 Daily Focus Report")
    if not st.session_state.history: st.info("Record at least one session to generate a report.")
    else:
        q=pd.DataFrame(st.session_state.history); avg=q.focus_score.mean(); total=q.duration.sum(); dis=q.distractions.mean(); sl=q.sleep.mean(); c1,c2,c3,c4=st.columns(4); c1.metric("Focus Score",f"{avg:.0f}/100"); c2.metric("Study Time",f"{total:.0f} min"); c3.metric("Distractions",f"{dis:.1f}"); c4.metric("Sleep",f"{sl:.1f} hrs"); st.write(f"You studied **{total:.0f} minutes** across **{len(q)} session(s)** with an average focus score of **{avg:.0f}/100**."); st.warning("📵 Average distractions are high.") if dis>=5 else st.success("✅ Average distractions are manageable."); st.warning("😴 Average sleep is low.") if sl<6 else st.success("😴 Recorded sleep is reasonable."); latest=q.iloc[-1]; st.info(f"🎯 Latest session: **{latest.focus_score}/100 ({level(latest.focus_level)})**"); st.subheader("💡 Next Session Recommendation"); [st.write(x) for x in recs(int(latest.focus_level),int(latest.distractions),float(latest.sleep),float(latest.duration),int(latest.hour))]

elif menu=="📥 Download Data":
    st.header("📥 Download Data")
    if st.session_state.history:
        st.download_button("⬇️ Download My Study History CSV",pd.DataFrame(st.session_state.history).to_csv(index=False),"my_study_history.csv","text/csv")
    st.download_button("⬇️ Download Training Dataset",data.to_csv(index=False),"student_focus_training_data.csv","text/csv")

st.markdown("---"); st.caption("Student Focus AI Chatbot | Python + Random Forest + Streamlit | Study Pattern Analysis & Personalized Recommendations")
