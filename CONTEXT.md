# Shopping Intelligence

This context turns private household purchase records into trustworthy shopping knowledge and assistance.

## Language

**Purchase History**:
The household's recorded shopping orders and items over time, including their dates, quantities, prices, and recorded statuses. Receipts are a source of this history, not the history itself.
_Avoid_: Receipt history, payment history

**Purchase Date**:
The delivery date used as the date of a purchase in the Shopping Assistant and its purchase history, by the household operator's chosen convention.
_Avoid_: Receipt issue date, payment date

**Shopping Assistant**:
A conversational interface that answers questions from authoritative shopping data and performs only explicitly permitted shopping actions.
_Avoid_: Chatbot, general assistant

**Conversation**:
A durable, ordered exchange between the household operator and the Shopping Assistant, including user, assistant, and tool records.
_Avoid_: Chat session, thread

**Response Attempt**:
One effort by the Shopping Assistant to answer a submitted message, including any read-tool activity. Retrying creates a new attempt for the same message while preserving the earlier incomplete attempt.
_Avoid_: New conversation when retrying a response

**Read Tool**:
An application-owned, bounded operation through which the Shopping Assistant retrieves authoritative shopping facts without direct database or archive access.
_Avoid_: Database tool, SQL tool, receipt tool

**Evidence**:
A stable reference connecting a fact returned to the Shopping Assistant with the corresponding order or product visible to the household operator.
_Avoid_: Citation when no inspectable record is linked

**Cloud Consent**:
The household operator's agreement to send a particular Conversation's messages and retrieved shopping facts to its selected cloud provider and model under the stated disclosure scope.
_Avoid_: Blanket consent for all conversations
