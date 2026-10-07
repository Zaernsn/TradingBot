# Password-reset email via Resend API

Password resets use the Resend HTTPS API exclusively. No SMTP host, port, username or password is required.

Set these in `.env` (development) or `.env.production` (production), then restart the backend:

```dotenv
RESEND_API_KEY=YOUR_RESEND_API_KEY
RESEND_FROM=WACG <noreply@your-verified-domain.example>
APP_PUBLIC_URL=https://your-app.example
```

Create an API key with email sending permission and verify your sending domain in Resend. Set `RESEND_FROM` to an address on that domain. Keep the API key out of source control and chat. Use Forgot password on the login page to request a link to your registered email address.

The backend calls `POST https://api.resend.com/emails` with an idempotency key derived from the reset token's hash. Reset tokens expire after 30 minutes and are single-use. Error logs never include credentials, recipients or reset URLs. Missing configuration returns a configuration error; provider errors preserve the account-neutral response.

References: [Resend Send Email API](https://resend.com/docs/api-reference/emails/send-email), [free allowance: 3,000 emails/month and 100/day](https://resend.com/docs/knowledge-base/account-quotas-and-limits).

Actual delivery requires a configured API key, verified sender and reachable app URL. Automated tests mock Resend and do not send emails.
