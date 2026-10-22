# Model Portfolio Rebalancing Guidelines

> Synthetic reference document for the AgentForge demo. Not investment advice.

## Rebalancing bands

Model portfolios are reviewed quarterly. A holding is rebalanced when its actual weight drifts more than 2 percentage points from target. A portfolio-level cash breach is corrected within three business days. Tactical tilts outside the strategic range require a written rationale from the portfolio manager and review by the Investment Risk Committee.

## Task creation

Portfolio operations create a rebalance task for every approved trade set. A task must include the portfolio identifier, the reason for the change, the target weights, the requesting advisor, and the approval reference. Operations must not execute a trade from an email or chat instruction alone. Every task is linked to the originating client record and retained for audit.

## Restricted and prohibited securities

The restricted list is maintained by Compliance. Purchases of restricted securities are blocked in the order management system. Securities under review for sanctions, controversy, or issuer distress require a second-line review. The platform must not recommend a prohibited security, even if a client requests it.

## Client-specific constraints

Advisors may apply client-specific constraints such as tax sensitivity, liquidity needs, or exclusion lists. Constraints must be recorded in the client profile before implementation. The portfolio manager must confirm that the resulting portfolio still satisfies the mandate and concentration limits.

## Escalation

An unresolved drift above 5 percentage points is escalated to the Head of Portfolio Operations and the Chief Investment Officer. A failed trade or reconciliation break is escalated within one hour. All escalations are logged with timestamps and owners.

## Segregation of duties

The person who creates a rebalance task cannot be the same person who approves it. Trade execution is performed by authorized operations staff only. The platform records requester, approver, executor, and timestamp for every action.
