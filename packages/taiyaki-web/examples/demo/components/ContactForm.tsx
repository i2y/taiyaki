
interface ContactFormProps {
  _errors?: Record<string, string[]>;
  _formData?: Record<string, string>;
  _csrfToken?: string;
  success?: boolean;
}

export default function ContactForm({ _errors, _formData, _csrfToken, success }: ContactFormProps) {
  const errors = _errors || {};
  const data = _formData || {};
  const inputStyle = "width: 100%; padding: 8px 12px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 14px; box-sizing: border-box;";
  const errorStyle = "color: #dc2626; font-size: 13px; margin-top: 4px;";

  if (success) {
    return (
      <div style="background: #ecfdf5; border: 2px solid #6ee7b7; border-radius: 8px; padding: 20px; text-align: center;">
        <p style="font-weight: 600; color: #065f46;">Message sent!</p>
      </div>
    );
  }

  return (
    <div>
      <taiyaki-head><title>Contact Form</title></taiyaki-head>
      <h1>Contact Form</h1>
      <p style="color: #666; margin-bottom: 24px;">With server-side validation and CSRF protection</p>
      <form method="POST" action="/form" style="display: flex; flex-direction: column; gap: 16px; max-width: 400px;">
        <input type="hidden" name="_csrf_token" value={_csrfToken || ""} />
        <div>
          <label style="font-weight: 600; display: block; margin-bottom: 4px;">Name</label>
          <input name="name" value={data.name || ""} style={inputStyle} />
          {errors.name ? <div style={errorStyle}>{errors.name[0]}</div> : null}
        </div>
        <div>
          <label style="font-weight: 600; display: block; margin-bottom: 4px;">Email</label>
          <input name="email" type="email" value={data.email || ""} style={inputStyle} />
          {errors.email ? <div style={errorStyle}>{errors.email[0]}</div> : null}
        </div>
        <div>
          <label style="font-weight: 600; display: block; margin-bottom: 4px;">Message</label>
          <textarea name="message" rows={4} style={inputStyle}>{data.message || ""}</textarea>
          {errors.message ? <div style={errorStyle}>{errors.message[0]}</div> : null}
        </div>
        <button
          type="submit"
          style="background: #7c3aed; color: white; border: none; padding: 10px 20px; border-radius: 6px; font-weight: 600; cursor: pointer;"
        >
          Send Message
        </button>
      </form>
    </div>
  );
}
