SHARED_STYLES = """
<style>
  /* Reset */
  body, table, td, a { -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }
  table, td { mso-table-lspace: 0pt; mso-table-rspace: 0pt; }
  img { -ms-interpolation-mode: bicubic; border: 0; outline: none; }

  body {
    margin: 0;
    padding: 0;
    background-color: #f4fbf9;
    font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    color: #0f1a14;
  }

  .wrapper {
    width: 100%;
    padding: 48px 16px;
    background-color: #f4fbf9;
    box-sizing: border-box;
  }

  .card {
    max-width: 560px;
    margin: 0 auto;
    background: #ffffff;
    border-radius: 14px;
    border: 1px solid #e2ebe6;
    overflow: hidden;
    box-shadow: 0 2px 16px rgba(15, 26, 20, 0.07);
  }

  /* Green accent bar at top of card */
  .card-accent {
    height: 4px;
    background: #2AB090;
  }

  .card-body {
    padding: 36px 40px 32px;
  }

  /* Logo */
  .logo {
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 22px;
    font-weight: bold;
    color: #0f1a14;
    letter-spacing: -0.03em;
    text-decoration: none;
    margin-bottom: 28px;
    display: block;
  }

  .logo-accent {
    color: #2AB090;
  }

  /* Heading */
  h2 {
    font-family: Georgia, 'Times New Roman', serif;
    margin: 0 0 10px;
    font-size: 22px;
    font-weight: bold;
    color: #0f1a14;
    letter-spacing: -0.02em;
    line-height: 1.35;
  }

  /* Body text */
  p {
    margin: 0 0 16px;
    font-size: 15px;
    color: #5e6e66;
    line-height: 1.65;
  }

  /* CTA Button */
  .btn-wrap {
    margin: 8px 0 28px;
  }

  .btn {
    display: inline-block;
    padding: 14px 32px;
    background-color: #2AB090;
    color: #ffffff !important;
    text-decoration: none;
    border-radius: 8px;
    font-size: 15px;
    font-weight: 700;
    font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
    letter-spacing: 0.01em;
    line-height: 1;
  }

  /* Note / small text */
  .note {
    font-size: 13px;
    color: #97a59e;
    line-height: 1.6;
  }

  .note strong {
    color: #5e6e66;
  }

  /* Fallback URL */
  .fallback-wrap {
    background: #f4fbf9;
    border-radius: 6px;
    padding: 10px 14px;
    margin-top: 8px;
  }

  .fallback {
    font-size: 12px;
    color: #97a59e;
    word-break: break-all;
    margin: 0;
    font-family: 'Courier New', Courier, monospace;
  }

  /* Divider */
  .divider {
    border: none;
    border-top: 1px solid #e2ebe6;
    margin: 28px 0;
  }

  /* Footer */
  .footer {
    font-size: 12px;
    color: #97a59e;
    text-align: center;
    margin-top: 24px;
    line-height: 1.6;
  }

  @media (max-width: 600px) {
    .card-body {
      padding: 28px 24px 24px;
    }
  }
</style>
"""


def verification_email(first_name: str, verify_url: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Verify your Languni email</title>
  {SHARED_STYLES}
</head>
<body>
  <div class="wrapper">
    <div class="card">
      <div class="card-accent"></div>
      <div class="card-body">

        <a href="#" class="logo">Lang<span class="logo-accent">uni</span></a>

        <h2>Verify your email address</h2>
        <p>Hi {first_name},</p>
        <p>Thanks for signing up! Click the button below to verify your email and activate your Languni account.</p>

        <div class="btn-wrap">
          <a href="{verify_url}" class="btn" style="background-color:#2AB090;color:#ffffff;text-decoration:none;display:inline-block;padding:14px 32px;border-radius:8px;font-size:15px;font-weight:700;">
            Verify Email
          </a>
        </div>

        <p class="note">This link expires in <strong>24 hours</strong>. If you didn't create a Languni account, you can safely ignore this email.</p>

        <hr class="divider" />

        <p class="note">Having trouble with the button? Copy and paste this link into your browser:</p>
        <div class="fallback-wrap">
          <p class="fallback">{verify_url}</p>
        </div>

      </div>
    </div>
    <p class="footer">© Languni &nbsp;·&nbsp; You received this because you signed up for an account.</p>
  </div>
</body>
</html>"""


def reset_password_email(first_name: str, reset_url: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Reset your Languni password</title>
  {SHARED_STYLES}
</head>
<body>
  <div class="wrapper">
    <div class="card">
      <div class="card-accent"></div>
      <div class="card-body">

        <a href="#" class="logo">Lang<span class="logo-accent">uni</span></a>

        <h2>Reset your password</h2>
        <p>Hi {first_name},</p>
        <p>We received a request to reset the password for your Languni account. Click the button below to choose a new one.</p>

        <div class="btn-wrap">
          <a href="{reset_url}" class="btn" style="background-color:#2AB090;color:#ffffff;text-decoration:none;display:inline-block;padding:14px 32px;border-radius:8px;font-size:15px;font-weight:700;">
            Reset Password
          </a>
        </div>

        <p class="note">This link expires in <strong>1 hour</strong>. If you didn't request a password reset, you can safely ignore this email — your password won't change.</p>

        <hr class="divider" />

        <p class="note">Having trouble with the button? Copy and paste this link into your browser:</p>
        <div class="fallback-wrap">
          <p class="fallback">{reset_url}</p>
        </div>

      </div>
    </div>
    <p class="footer">© Languni &nbsp;·&nbsp; You received this because a password reset was requested for your account.</p>
  </div>
</body>
</html>"""
