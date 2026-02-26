SHARED_STYLES = """
<style>
  body { margin: 0; padding: 0; background-color: #f4f4f5; font-family: Arial, sans-serif; }
  .wrapper { padding: 40px 16px; }
  .card { max-width: 560px; margin: 0 auto; background: #ffffff; border-radius: 12px; padding: 40px 36px; }
  .logo { font-size: 22px; font-weight: bold; color: #4f46e5; margin-bottom: 28px; }
  h2 { margin: 0 0 12px; font-size: 20px; color: #111827; }
  p { margin: 0 0 16px; font-size: 15px; color: #374151; line-height: 1.6; }
  .btn { display: inline-block; margin: 8px 0 24px; padding: 13px 30px; background-color: #4f46e5; color: #ffffff !important; text-decoration: none; border-radius: 7px; font-size: 15px; font-weight: bold; }
  .note { font-size: 13px; color: #6b7280; }
  .fallback { font-size: 12px; color: #9ca3af; word-break: break-all; margin-top: 4px; }
  .divider { border: none; border-top: 1px solid #e5e7eb; margin: 28px 0; }
  .footer { font-size: 12px; color: #9ca3af; text-align: center; margin-top: 24px; }
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
      <div class="logo">Languni</div>
      <h2>Verify your email address</h2>
      <p>Hi {first_name},</p>
      <p>Thanks for signing up! Click the button below to verify your email address and activate your account.</p>
      <a href="{verify_url}" class="btn">Verify Email</a>
      <p class="note">This link expires in <strong>24 hours</strong>. If you didn't create an account, you can safely ignore this email.</p>
      <hr class="divider" />
      <p class="note">Having trouble with the button? Copy and paste this link into your browser:</p>
      <p class="fallback">{verify_url}</p>
    </div>
    <div class="footer">© Languni &nbsp;·&nbsp; You received this because you signed up for an account.</div>
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
      <div class="logo">Languni</div>
      <h2>Reset your password</h2>
      <p>Hi {first_name},</p>
      <p>We received a request to reset your password. Click the button below to choose a new one.</p>
      <a href="{reset_url}" class="btn">Reset Password</a>
      <p class="note">This link expires in <strong>1 hour</strong>. If you didn't request a password reset, you can safely ignore this email — your password won't change.</p>
      <hr class="divider" />
      <p class="note">Having trouble with the button? Copy and paste this link into your browser:</p>
      <p class="fallback">{reset_url}</p>
    </div>
    <div class="footer">© Languni &nbsp;·&nbsp; You received this because a password reset was requested for your account.</div>
  </div>
</body>
</html>"""
