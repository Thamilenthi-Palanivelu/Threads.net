from typing import Annotated, TypedDict, List
import operator
import time
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from openai import OpenAI
import re

# Set up the OpenAI client to use the local LLM
client = OpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")

class StatusUpdateState(TypedDict):
    messages: Annotated[List[HumanMessage | AIMessage | SystemMessage], operator.add]
    draft: str
    character_count: int
    status: str
    versions: List[str]
    researcher_analysis: str
    editor_feedback: str
    iteration_count: int
    draft_analysis: str  # Added for the draft_analyzer
    editor_history: List[str]  # To store editor's feedback history
    start_time: float  # Added for duration tracking

def increment_and_check_iterations(state: StatusUpdateState) -> StatusUpdateState:
    state["iteration_count"] += 1
    if state["iteration_count"] > 300:
        print("Maximum overall iterations reached. Forcing completion.")
        return {"status": "approved"}
    return {}

def user(state: StatusUpdateState) -> StatusUpdateState:
    state.update(increment_and_check_iterations(state))
    print(f"User node: Current status - {state['status']}")

    def get_multiline_input(prompt):
        print(prompt)
        print("Enter your text below. You can use multiple lines.")
        print("When you're done, enter '//done' on a new line.")
        lines = []
        while True:
            line = input()
            if line.strip().lower() == '//done':
                break
            lines.append(line)
        return "\n".join(lines)

    if state["status"] == "initial":
        initial_draft = get_multiline_input("Please enter your initial draft for the status update:")
        print("User has submitted the initial draft. Sending it to the draft analyzer.\n") 
        # Record the start time when the initial draft is submitted
        state["start_time"] = time.time()
        return {"draft": initial_draft, "status": "draft_submitted"}

    elif state["status"] == "user_approval":
        print("\nThe status update is ready for final approval. Asking the user the following:\n")
        print("\nFinal draft for approval:")
        print(state["draft"])
        while True:
            approval = input("Do you approve this draft? (yes/no): ").lower()
            if approval in ['yes', 'no']:
                break
            print("Please enter 'yes' or 'no'.")

        if approval == 'yes':
            print("User approved the final draft\n")
            return {"status": "approved"}
        else:
            feedback = get_multiline_input("Please provide feedback for revision:")
            print(f"User requested revision: {feedback}\n")
            return {"editor_feedback": feedback, "status": "needs_revision"}

    return {}


def researcher(state: StatusUpdateState) -> StatusUpdateState:
    state.update(increment_and_check_iterations(state))
    print("The Researcher is analyzing the draft...\n")
    prompt = f"""
    You are a researcher tasked with analyzing the following draft of a threads.net status update:

    Draft: {state['draft']}

    Instructions:
    * Your role is to provide insights and information about the potential target audience, relevant topics, and potential opinion groups that might be interested in this status update.
    * **Do NOT provide any guidance on writing style, structure, or specific wording.** Your focus is purely on research and analysis. 

    Provide information on the following:
    * **Target Audience:** Who are the most likely audiences for this status update on Threads.net? Consider demographics, interests, and online behavior. Be specific and provide examples.
    * **Relevant Topics:** What broader topics or themes does this status update relate to? Identify any trending topics or discussions on Threads.net that might be relevant.
    * **Opinion Groups:**  Are there any specific groups or communities on Threads.net that might have strong opinions or perspectives on the subject of this status update? 
    * **Key Insights:**  Based on your research, are there any additional insights or data points that could be valuable for the writer to consider?

    Threads.net Profile:
    Threads is a text-based social networking service developed by Meta Platforms (formerly Facebook). Launched in July 2023, it is designed for sharing text updates and joining public conversations. Users can post up to 500 characters of text and include links, photos, and videos up to 5 minutes in length. It is closely linked to Instagram, allowing users to easily share their Threads posts to their Instagram stories. Threads is also considered a competitor to Twitter.com.

    Focus solely on providing research-based information and avoid making any writing suggestions. 
    """
    completion = client.chat.completions.create(
        model="bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    analysis = completion.choices[0].message.content
    print(f"Researcher Analysis: {analysis}")
    print("The Researcher has finished the analysis. Sending it to the Writer.\n")
    return {"researcher_analysis": analysis, "status": "research_complete"}

def draft_analyzer(state: StatusUpdateState) -> StatusUpdateState:
    state.update(increment_and_check_iterations(state))
    print("The Draft Analyzer is reviewing the status update...\n")
    prompt = f"""
    Analyze the following initial draft of a status update for threads.net and provide a detailed breakdown, ensuring there are no subheadings:

    Draft: {state['draft']}

    Instructions:
    * Break down the draft into its key components (Hook, Introduction, Main Content, Value Proposition, Call to Action).
    * Analyze each component's effectiveness and adherence to the guidelines below.
    * Provide specific suggestions for improvement for each component.
    * **Never propose a potential version of the status update. Your role is strictly to analyze and provide feedback, not to write or suggest revisions.**

    Guidelines for a Perfect Status Update:
    * Conciseness: The update should be within 500 characters.
    * Text-Only: No images or non-text elements.
    * No Subheadings: The update should be written in a single paragraph without subheadings. 
    * Clarity:  The message should be clear, concise, and easy to understand.
    * Engagement:  The update should be interesting and engaging for the target audience.
    * Opinionated: It should take a clear and opinionated stance on the topic.
    * No External References: Do not include hashtags, links, or URLs.
    - Conciseness and Jargon:  Avoid unnecessary words and technical jargon. 
    - Single Paragraph: Ensure the update is written in a single paragraph, without headings. 

    Focus on providing constructive feedback and suggestions for improvement. Your analysis should help the writer understand the strengths and weaknesses of their initial draft.
    """
    completion = client.chat.completions.create(
        model="bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    analysis = completion.choices[0].message.content
    print(f"Draft Analysis: {analysis}")
    print("The Draft Analyzer has finished reviewing. Sending insights to the Writer.\n")
    return {"draft_analysis": analysis, "status": "draft_analyzed"}

def writer(state: StatusUpdateState) -> StatusUpdateState:
    state.update(increment_and_check_iterations(state))
    print("The Writer is now working on the status update, incorporating feedback...\n")
    researcher_analysis = state.get('researcher_analysis', 'No research analysis available')
    editor_feedback = state.get('editor_feedback', 'No editor feedback yet')
    draft_analysis = state.get('draft_analysis', 'No draft analysis available.')

    # Build version history string, including character count rejections
    version_history_str = ""
    for i, version in enumerate(state["versions"]):
        if i == 0:  # Skip the initial empty draft
            continue
        rejection_reason = ""
        if i == len(state["versions"]) - 1:
            rejection_reason = state["editor_feedback"] 
        elif len(version) > 500:  # Check if rejected due to character count
            rejection_reason = f"Exceeded character limit ({len(version)} characters)."
        else:
            rejection_reason = state["editor_history"][i - 1]
        version_history_str += f"## Version {i}:\n{version}\n**Reason for Rejection:** {rejection_reason}\n\n"

    prompt = f"""
    You are a professional writer creating a text-only status update for threads.net. Your task is to create or edit based on the following information, ensuring there are no subheadings:

    Original draft: {state['draft']}
    Researcher's analysis: {researcher_analysis}
    Editor's feedback: {editor_feedback} 
    Draft Analysis: {draft_analysis}
    Previous Versions and Rejection Reasons:
    {version_history_str}

    Instructions:
    1. If the researcher has provided analysis, incorporate relevant insights into your draft.
    2. If the editor has provided feedback, carefully consider their suggestions and make appropriate revisions.
    3. Carefully review the previous versions and the reasons they were rejected. Avoid repeating the same mistakes.

    Guidelines for the Perfect Status Update Structure:
    1. Hook (10% of content, aim for 5-10 words for this section because we are trying to aim to having the total character count for the status update within 500 characters): Capture attention with a compelling fact, statistic, or provocative question.
    2. Introduction (15% of content, aim for 8-15 words for this section because we are trying to aim to having the total character count for the status update within 500 characters): Briefly summarize the key point of the news in 1-2 sentences.
    3. Main Content (50% of content, aim for 25-40 words for this section because we are trying to aim to having the total character count for the status update within 500 characters): Expand on the introduction with details, insights, or analysis.
    4. Value Proposition (20% of content, aim for 10-20 words for this section because we are trying to aim to having the total character count for the status update within 500 characters): Highlight the significance or impact of the news.
    5. Call to Action (5% of content, aim for 3-5 words for this section because we are trying to aim to having the total character count for the status update within 500 characters): End with a very brief question to encourage engagement.

    Additional Guidelines:
    - Ensure the update is within 500 characters.
    - Only produce text content. No images or non-text elements.
    - Never use hashtags.
    - Do NOT use links or URLs.
    - Do NOT mention or imply additional information beyond what's in the status update.
    - Be opinionated and take a clear stance on the topic.
    - Focus on using abbreviations, compared to long technical jargon.
    - Do not write a title or heading.
    - Write in 1 paragraph only. This means NO new lines, NO multiple paragraphs, just a single block of text.
    - Do not include any subheadings.

    To ensure conciseness, consider these techniques:
    - **Use strong verbs and active voice.**
    - **Eliminate unnecessary words and phrases.** 
    - **Replace long phrases with shorter equivalents.**
    - **Prioritize the most impactful information.**
    - **Focus on the core message and key details.**

    Please provide your text-only, opinionated status update following this structure, incorporating insights from the researcher, addressing editor feedback, ensuring factual accuracy, and using the following format:

    RESPONSE_START
    [Write your status update here]
    RESPONSE_END
    <-stop-> 
    """

    completion = client.chat.completions.create(
        model="bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        stop=["<-stop->"]  # Set the stop string
    )
    new_draft = completion.choices[0].message.content

    # Extract the status update from the response
    new_draft = new_draft.split("RESPONSE_START")[1].split("RESPONSE_END")[0].strip()

    char_count = len(new_draft)
    print(f"Writer's Draft: {new_draft}")

    # Character count check moved here:
    if char_count <= 500:
        state["versions"].append(new_draft)
        print("The Writer has finished and is sending the draft to the Editor.\n")
        return {"draft": new_draft, "current_draft": new_draft, "character_count": char_count, "status": "ready_for_editor"}
    else:
        excess_chars = char_count - 500
        print(f"The Writer is making further revisions to meet the character limit. The draft is {excess_chars} characters too long.\n")
        state["editor_feedback"] += f"\nPlease shorten the draft to be within 500 characters. It is currently {excess_chars} characters too long. Focus on the most critical information and remove any unnecessary details."
        return {"status": "editing", "current_draft": new_draft}

def editor(state: StatusUpdateState) -> StatusUpdateState:
    state.update(increment_and_check_iterations(state))
    print("The Editor is reviewing the draft...\n")
    prompt = f"""
    You are a professional editor reviewing a text-only status update for threads.net. 
    Your goal is to collaboratively work with the writer to produce a high-quality status update. Provide constructive feedback to improve the draft while ensuring it adheres to the following guidelines:

    Draft: {state['draft']}

    Review the draft based on the following criteria and provide a score from 0 to 10, where 0 is the lowest and 10 is the highest. 
    A score above 5 indicates approval. Provide constructive feedback to help the writer improve the draft, 
    regardless of the score. 

    Review Criteria:
    * **Hook:** Does it capture attention with a compelling fact, statistic, or provocative question?
    * **Introduction:** Does it briefly summarize the key point of the news?
    * **Main Content:** Does it expand on the introduction with details, insights, or analysis?
    * **Value Proposition:** Does it highlight the significance or impact of the news?
    * **Call to Action:** Does it end with a brief question to encourage engagement?

    Additional Guidelines:
    - Content Type: Is it text-only, without images or extraneous elements?
    - No External References: Does it avoid using hashtags, links, or URLs?
    - Conciseness: Is the language clear and concise, avoiding jargon?
    - Opinion: Does it express a clear and opinionated stance?
    - Structure: Is it written in a single paragraph without subheadings or titles? 

    Feedback Instructions:
    * Provide specific suggestions for improvement, including examples or rephrasing ideas.
    * Highlight both the strengths and weaknesses of the draft.
    * Deliver your feedback in a professional and respectful tone.
    * Clearly state the score you assigned to the draft.
    * Do not suggest adding hashtags. 
    * **Never propose a potential version of the status update. Your role is strictly to analyze and provide feedback, not to write or suggest revisions.**

    Example:
    Score: 7
    Feedback: The draft is well-written and engaging, but the hook could be stronger. Consider starting with a more surprising statistic or a thought-provoking question. 
    """
    completion = client.chat.completions.create(
        model="bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    feedback = completion.choices[0].message.content
    print(f"Editor Feedback: {feedback}")

    # Extract the score from the feedback
    score = extract_score(feedback) 
    print(f"Editor Score: {score}")

    # Append feedback to editor_history
    state["editor_history"].append(feedback)

    if score > 5:
        # Record the time when the editor approves
        editor_approval_time = time.time()
        duration = editor_approval_time - state["start_time"]
        print(f"Time from initial draft to editor approval: {int(duration // 60)} minutes and {duration % 60:.2f} seconds")
        print("The Editor has approved the draft. Sending it to the User for final approval.\n")
        return {"status": "user_approval", "editor_feedback": feedback}
    else:
        print("The Editor has requested revisions. Sending the draft back to the Writer.\n")
        return {"status": "needs_revision", "editor_feedback": feedback}

# Helper Function to Extract Score:
def extract_score(feedback: str) -> int:
    """Extracts the score from the editor's feedback."""

    # Try different patterns to find the score
    patterns = [
        r"Score:\s*(\d+)",  # Original pattern
        r"**Score:**\s*(\d+)",  # Pattern with bold formatting
        r"Score\s*:\s*(\d+)",  # Pattern with different spacing
        # Add more patterns as needed based on observed LLM responses
    ]

    for pattern in patterns:
        match = re.search(pattern, feedback, re.IGNORECASE)
        if match:
            return int(match.group(1))

    # If no score is found, return 0 and print a warning
    print("Warning: No score found in editor feedback. Assuming needs revision.")
    return 0

def should_continue(state: StatusUpdateState) -> str:
    print(f"Deciding next step. Current status: {state['status']}")
    if state["iteration_count"] > 30:
        return END
    if state["status"] == "approved":
        return END
    elif state["status"] == "draft_submitted":
        return "draft_analyzer"  
    elif state["status"] == "draft_analyzed":
        return "researcher"
    elif state["status"] == "research_complete": 
        return "writer"
    elif state["status"] == "needs_revision":
        return "writer"  # Writer should receive user feedback as well
    elif state["status"] == "ready_for_editor": # Changed from ready_for_fact_check
        return "editor"
    elif state["status"] == "user_approval":
        return "user"
    elif state["status"] == "editing":
        return "writer"
    else:
        print(f"Error: Unhandled status '{state['status']}' in should_continue function.")
        return END

# Create the graph
workflow = StateGraph(StatusUpdateState)

# Add nodes (Removed fact_checker node)
workflow.add_node("user", user)
workflow.add_node("researcher", researcher)
workflow.add_node("draft_analyzer", draft_analyzer)
workflow.add_node("writer", writer)
workflow.add_node("editor", editor)

# Set up the flow
workflow.set_entry_point("user")
workflow.add_conditional_edges("user", should_continue)
workflow.add_conditional_edges("researcher", should_continue)
workflow.add_conditional_edges("draft_analyzer", should_continue)
workflow.add_conditional_edges("writer", should_continue)
# Removed fact_checker edge
workflow.add_conditional_edges("editor", should_continue)

# Compile the graph
app = workflow.compile()

def main():
    # Initialize the state with an empty initial draft.
    # The user will be prompted for the draft within the 'user' node function.
    initial_draft = ""

    # Initialize the state
    initial_state = {
        "messages": [SystemMessage(content="You are helping create a status update.")],
        "draft": initial_draft,
        "current_draft": "",
        "character_count": len(initial_draft),
        "status": "initial",
        "versions": [initial_draft],
        "researcher_analysis": "",
        "editor_feedback": "",
        "iteration_count": 0,
        "draft_analysis": "",  
        "editor_history": [],
        "start_time": 0.0  
    }

    # Run the graph with increased recursion limit
    app_with_config = app.with_config({"recursion_limit": 500})
    result = app_with_config.invoke(initial_state)

    # Print the final result
    print("\nFinal State:")
    print(f"Approved Draft: {result['draft']}")
    print(f"Character Count: {result['character_count']}")
    print(f"Final Status: {result['status']}")
    print(f"Total Iterations: {result['iteration_count']}")
    print("\nVersion History:")
    for i, version in enumerate(result['versions'], 1):
        print(f"Version {i}: {version[:50]}...")  # Print first 50 characters of each version
    print("\nResearcher Analysis:")
    print(result.get('researcher_analysis', 'No researcher analysis available'))
    print("\nFinal Editor Feedback:")
    print(result.get('editor_feedback', 'No editor feedback available'))
    print("\nDraft Analysis:")  # Added for draft_analyzer
    print(result.get('draft_analysis', 'No draft analysis available'))
    print("\nMessages:")
    for message in result['messages']:
        print(f"- {message.content}")

if __name__ == "__main__":
    main()
