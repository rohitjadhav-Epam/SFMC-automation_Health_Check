import streamlit as st
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
from datetime import datetime
import io
from difflib import SequenceMatcher

st.set_page_config(page_title="Automation Governance Tool", layout="wide")
st.title("🤖 Automation Usage & Governance Analyzer")

uploaded_file = st.file_uploader("📤 Upload your automation log CSV file", type=["csv"])

@st.cache_data
def load_data(uploaded_file):
    df = pd.read_csv(uploaded_file, sep=None, engine='python', parse_dates=['CreatedDate', 'LastRunTime'])
    df.columns = df.columns.str.strip()
    df['LastRunTime'] = pd.to_datetime(df['LastRunTime'], errors='coerce')
    df['CreatedDate'] = pd.to_datetime(df['CreatedDate'], errors='coerce')
    df['RoundedRunTime'] = df['LastRunTime'].dt.round('h')
    df['ScheduleGroup'] = df['ScheduledFrequency'].str.split(',').str[0].str.strip()
    return df

if uploaded_file:
    df = load_data(uploaded_file)

    now = pd.Timestamp.now()
    df['LastRunAgeDays'] = (now - df['LastRunTime']).dt.days
    df['IsActive'] = df['LastRunAgeDays'] <= 30
    df['HasNeverRun'] = df['LastRunTime'].isna()
    df['AutomationAgeGroup'] = pd.cut(df['LastRunAgeDays'],
        bins=[-1, 30, 90, 180, 365, float('inf')],
        labels=["<1 mo", "1–3 mo", "3–6 mo", "6–12 mo", ">1 yr"]
    )

    df['SuccessRate'] = df['30DaySuccessRate']
    df['ErrorRate'] = df['30DayErrorCount'] / df['30DayRunCount'].replace(0, pd.NA)
    df['SkipRate'] = df['30DaySkipCount'] / df['30DayRunCount'].replace(0, pd.NA)
    df['EfficiencyScore'] = df['30DayCompletionCount'] / df['30DayRunCount'].replace(0, pd.NA)
    df['AnnualizedRunCount'] = df['30DayRunCount'] * 12

    def suggest_action(row):
        if row['HasNeverRun'] and row['CreatedDate'] < now - pd.Timedelta(days=90):
            return "Created But Never Run"
        elif row['LastRunAgeDays'] > 180:
            return "Stale – Consider Archiving"
        elif pd.isna(row['LastRunTime']):
            return "No Run History"
        elif row['30DayRunCount'] == 0:
            return "Inactive"
        elif row['ErrorRate'] and row['ErrorRate'] > 0.5:
            return "Error-Prone"
        elif row['IsActive'] and 'every hour' in str(row['ScheduledFrequency']).lower():
            return "Review High Frequency"
        elif row['EfficiencyScore'] and row['EfficiencyScore'] < 0.5 and row['30DayRunCount'] > 10:
            return "Inefficient"
        elif row['AnnualizedRunCount'] > 50000:
            return "Excessive Annual Volume"
        else:
            return "Keep"

    df['SuggestedAction'] = df.apply(suggest_action, axis=1)

    # Sidebar filters
    st.sidebar.header("🔍 Filters")
    bu_filter = st.sidebar.multiselect("Filter by Business Unit", df['BusinessUnitName'].dropna().unique())
    action_filter = st.sidebar.multiselect("Filter by Suggested Action", df['SuggestedAction'].dropna().unique())
    # Scheduled Frequency filter with 'Blank' support
    df['ScheduleGroupFilter'] = df['ScheduleGroup'].fillna('Blank')
    schedule_options = df['ScheduleGroupFilter'].unique()

    scheduled_filter = st.sidebar.multiselect(
        "Filter by Scheduled Frequency (first part only)",
        options=schedule_options
)

    search = st.sidebar.text_input("Search by Automation Name")

    if bu_filter:
        df = df[df['BusinessUnitName'].isin(bu_filter)]
    if action_filter:
        df = df[df['SuggestedAction'].isin(action_filter)]
    if scheduled_filter:
        df = df[df['ScheduleGroupFilter'].isin(scheduled_filter)]
    if search:
        df = df[df['AutomationName'].str.contains(search, case=False, na=False)]

    # 📋 All Automations After Filters (new section)
    st.markdown(f"### 📋 All Automations After Filters ({len(df)})")
    st.dataframe(df[['AutomationName', 'BusinessUnitName', 'ScheduledFrequency', 'LastRunTime', 'SuggestedAction']])

    # 📊 Summary by Business Unit
    st.markdown("### 📊 Summary by Business Unit")
    bu_summary = df.groupby('BusinessUnitName').agg(
        TotalAutomations=('AutomationName', 'count'),
        ActiveAutomations=('IsActive', 'sum'),
        AvgSuccessRate=('SuccessRate', 'mean'),
        TotalRuns=('30DayRunCount', 'sum'),
        EstimatedAnnualRuns=('AnnualizedRunCount', 'sum')
    ).reset_index()
    st.dataframe(bu_summary)

    st.markdown("### 🚦 Business Unit Overuse Risk")
    st.bar_chart(bu_summary.set_index('BusinessUnitName')['EstimatedAnnualRuns'])

    # 📊 Automation Age Distribution
    age_counts = df['AutomationAgeGroup'].value_counts().sort_index()
    st.markdown(f"### 📊 Automation Age Distribution ({age_counts.sum()} total automations)")
    st.bar_chart(age_counts)

    # 📊 Efficiency Score Distribution
    st.markdown("### 📊 Efficiency Score Distribution")
    fig_eff, ax_eff = plt.subplots()
    sns.histplot(df['EfficiencyScore'].dropna(), bins=20, kde=True, ax=ax_eff)
    ax_eff.set_title("Automation Efficiency Score Distribution")
    st.pyplot(fig_eff)

    # ⏱ High Frequency Automations
    hourly = df[df['ScheduledFrequency'].str.contains("every hour", case=False, na=False)]
    st.markdown(f"### ⏱ High Frequency Automations ({len(hourly)})")
    st.dataframe(hourly[['AutomationName', 'BusinessUnitName', 'ScheduledFrequency', 'LastRunTime']])

    # ⚠️ Clashing Automations
    clashing = df[df.duplicated("RoundedRunTime", keep=False)].sort_values("RoundedRunTime")
    st.markdown(f"### ⚠️ Clashing Automations ({clashing['AutomationName'].nunique()} unique automations)")
    st.dataframe(clashing[['AutomationName', 'BusinessUnitName', 'LastRunTime', 'RoundedRunTime']])

    # 🧹 Flagged Automations
    flagged = df[df['SuggestedAction'] != 'Keep']
    st.markdown(f"### 🧹 Inactive / Error-Prone / Redundant ({len(flagged)})")
    st.dataframe(flagged[['AutomationName', 'BusinessUnitName', 'SuggestedAction', 'LastRunTime', '30DayRunCount', 'ErrorRate']])

    # 🧠 Suggested Merges
    def string_similarity(a, b):
        return SequenceMatcher(None, a, b).ratio()

    similar_groups = []
    seen = set()
    names = df['AutomationName'].dropna().unique()
    for name in names:
        if name in seen:
            continue
        group = [other for other in names if string_similarity(name, other) >= 0.85 and other != name]
        if group:
            group_set = set([name] + group)
            if not group_set.issubset(seen):
                similar_groups.append(group_set)
                seen.update(group_set)

    st.markdown(f"### 🧠 Suggested Merges – Similar Automation Groups ({len(similar_groups)})")
    for idx, group in enumerate(similar_groups[:10], 1):
        st.markdown(f"**Group {idx}:** {', '.join(sorted(group))}")

    # 📈 Top 10 Error-Prone Automations
    top_errors = df.sort_values("ErrorRate", ascending=False).dropna(subset=['ErrorRate']).head(10)
    st.markdown(f"### 📈 Top 10 Error-Prone Automations (Top {len(top_errors)})")
    fig, ax = plt.subplots(figsize=(10, 5))
    sns.barplot(y="AutomationName", x="ErrorRate", data=top_errors, hue="AutomationName", palette="Reds_r", ax=ax, legend=False)
    ax.set_title("Top 10 Automations by Error Rate")
    st.pyplot(fig)

    # 📊 Suggested Action Breakdown
    st.markdown("### 📊 Suggested Action Breakdown")
    action_counts = df['SuggestedAction'].value_counts()
    fig2, ax2 = plt.subplots()
    ax2.pie(action_counts, labels=action_counts.index, autopct='%1.1f%%', startangle=90)
    ax2.axis('equal')
    st.pyplot(fig2)

    # ⏰ Rush Hour Detection
    st.markdown("### ⏰ Rush Hour Detection")
    df['HourOfDay'] = df['LastRunTime'].dt.hour
    rush_hour = df['HourOfDay'].value_counts().sort_index()
    st.bar_chart(rush_hour)

    # ⚠️ Timeout Risk
    st.markdown("### ⚠️ Long-Running Automation / Timeout Risk")
    if 'RunDurationMinutes' in df.columns:
        timeout_risk = df[df['RunDurationMinutes'] >= 50]
        st.dataframe(timeout_risk[['AutomationName', 'BusinessUnitName', 'RunDurationMinutes', 'LastRunTime']])

    # 📈 Execution Timeline Chart
    st.markdown("### 📈 Execution Timeline Chart")
    timeline_df = df[['AutomationName', 'BusinessUnitName', 'LastRunTime']].dropna()
    fig_timeline, ax_timeline = plt.subplots(figsize=(10, 6))
    sns.scatterplot(data=timeline_df, x='LastRunTime', y='AutomationName', hue='BusinessUnitName', s=60, ax=ax_timeline)
    ax_timeline.set_title("Automation Execution Timeline")
    ax_timeline.set_xlabel("Last Run Time")
    ax_timeline.set_ylabel("Automation Name")
    st.pyplot(fig_timeline)

    # 📥 Export Excel
    st.markdown("### 📤 Download Full Annotated Data")
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Full Data')
        hourly.to_excel(writer, index=False, sheet_name='High Frequency')
        flagged.to_excel(writer, index=False, sheet_name='Flagged')
        clashing.to_excel(writer, index=False, sheet_name='Clashing')

    st.download_button("📥 Download Excel Report", data=output.getvalue(), file_name="automation_analysis.xlsx")

else:
    st.info("📎 Upload your CSV file to begin analysis.")
