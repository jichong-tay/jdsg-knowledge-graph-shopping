# Shopping Intelligence

This context turns private household purchase records into trustworthy shopping knowledge and assistance.

## Language

**Purchase History**:
The household's recorded shopping orders and items over time, including their dates, quantities, prices, and recorded statuses. Receipts are a source of this history, not the history itself.
_Avoid_: Receipt history, payment history

**Product**:
A specific shopping item with its own variant and package size. Different Products retain separate identities even when grouped into the same Product Family.
_Avoid_: Product Family, category

**Product Family**:
A named grouping of the same product type across brands and package sizes, with materially different types kept separate. Member Products retain their identities and individual purchase details while their purchase history can be considered together.
_Avoid_: Product, alias

**Family Membership**:
An assertion that a Product belongs to a Product Family, assessed against that Family's definition. Suggested memberships require review before contributing to family purchase history.
_Avoid_: Product merge, automatic synonym

**Purchase Date**:
The delivery date used as the date of a purchase in the Shopping Assistant, purchase history, and planned purchase-frequency analysis and predictions, by the household operator's chosen convention. Current records use the Scheduled Delivery Date; this does not establish actual arrival.
_Avoid_: Receipt issue date, payment date

**Order Date**:
The date an order was placed. It is distinct from its scheduled delivery date and from the time an order-related message was sent or received.
_Avoid_: Delivery date, email receipt date

**Scheduled Delivery Date**:
The date an order is expected to arrive according to its scheduled delivery slot. It does not establish when delivery actually occurred.
_Avoid_: Actual delivery date

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
