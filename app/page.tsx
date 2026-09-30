export default function Home() {
  const wa = process.env.NEXT_PUBLIC_WHATSAPP_NUMBER;
  return (
    <main className="wrap">
      <h1>Your complaint doesn’t end when you file it.</h1>
      <p className="lede">It ends when it’s fixed. Send Awaaz a voice note, photo or message on WhatsApp with your location. We file it with the right department, track it, and escalate only with your approval.</p>
      {wa ? <a className="btn primary" href={`https://wa.me/${wa.replace(/\D/g, '')}`}>Message Awaaz on WhatsApp</a> : null}
    </main>
  );
}
