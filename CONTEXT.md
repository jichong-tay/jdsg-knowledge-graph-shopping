# Shopping Intelligence

This context turns private household purchase records into trustworthy shopping knowledge and assistance.

## Language

**Shopping Assistant**:
A conversational interface that answers questions from authoritative shopping data and performs only explicitly permitted shopping actions.
_Avoid_: Chatbot, general assistant

**Conversation**:
A durable, ordered exchange between the household operator and the Shopping Assistant, including user, assistant, and tool records.
_Avoid_: Chat session, thread

**Read Tool**:
An application-owned, bounded operation through which the Shopping Assistant retrieves authoritative shopping facts without direct database or archive access.
_Avoid_: Database tool, SQL tool

**Evidence**:
A stable reference connecting a fact returned to the Shopping Assistant with the corresponding order or product visible to the household operator.
_Avoid_: Citation when no inspectable record is linked
