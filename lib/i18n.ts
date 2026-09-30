import type { Language } from './types';

type L = 'en' | 'ur-Latn' | 'ur';
type Msg = Record<L, (x: any) => string>;
const pick = (lang: string): L => (lang === 'ur' ? 'ur' : lang === 'en' ? 'en' : 'ur-Latn'); // Punjabi → Roman Urdu replies

const M = {
  welcome: {
    en: () => "Assalam o alaikum! Send a voice note, photo or message about a problem in your area, and share your location. I'll file it with the right department and follow it until it's fixed.",
    'ur-Latn': () => 'Assalam o alaikum! Apne ilaqe ke masle ke baare mein voice note, tasveer ya message bhejein aur location share karein. Main sahi idare mein shikayat darj karke hal hone tak peecha karunga.',
    ur: () => 'السلام علیکم! اپنے علاقے کے مسئلے کے بارے میں وائس نوٹ، تصویر یا پیغام بھیجیں اور لوکیشن شیئر کریں۔ میں درست ادارے میں شکایت درج کر کے حل ہونے تک پیروی کروں گا۔',
  },
  whereIs: {
    en: () => 'Where is this problem? Tap 📎 → Location and send the spot (current location or pick it on the map).',
    'ur-Latn': () => 'Yeh masla kahan hai? 📎 → Location dabayein aur jagah bhejein (mojooda location ya map par chunein).',
    ur: () => 'یہ مسئلہ کہاں ہے؟ 📎 ← لوکیشن دبائیں اور جگہ بھیجیں (موجودہ لوکیشن یا نقشے پر منتخب کریں)۔',
  },
  locationSaved: {
    en: () => 'Location saved. Now tell me what the problem is.',
    'ur-Latn': () => 'Location mil gayi. Ab batayein masla kya hai.',
    ur: () => 'لوکیشن مل گئی۔ اب بتائیں مسئلہ کیا ہے۔',
  },
  cantHear: {
    en: () => "I couldn't understand the voice note. Please type one line about the problem.",
    'ur-Latn': () => 'Voice note samajh nahi aaya. Barah-e-karam masle ke baare mein ek line likh dein.',
    ur: () => 'وائس نوٹ سمجھ نہیں آیا۔ براہِ کرم مسئلے کے بارے میں ایک لائن لکھ دیں۔',
  },
  urgent: {
    en: (x: { helpline?: string }) => `This sounds dangerous. Keep away from it and call Rescue 1122 now${x.helpline ? ` (or ${x.helpline})` : ''}. I'm filing your complaint as urgent.`,
    'ur-Latn': (x: { helpline?: string }) => `Yeh khatarnak lag raha hai. Is se door rahein aur abhi Rescue 1122${x.helpline ? ` (ya ${x.helpline})` : ''} par call karein. Main shikayat urgent ke taur par file kar raha hoon.`,
    ur: (x: { helpline?: string }) => `یہ خطرناک لگ رہا ہے۔ اس سے دور رہیں اور ابھی ریسکیو 1122${x.helpline ? ` (یا ${x.helpline})` : ''} پر کال کریں۔ میں شکایت ہنگامی طور پر درج کر رہا ہوں۔`,
  },
  match: {
    en: (x: { n: number; id: string; d: number }) => `${x.n} neighbors already reported this (${x.id}, open for ${x.d} days).\nReply 1 to add your voice, or 2 if it's a different problem.`,
    'ur-Latn': (x: { n: number; id: string; d: number }) => `${x.n} parosi pehle hi yeh masla report kar chuke hain (${x.id}, ${x.d} din se khula).\nApni awaaz shamil karne ke liye 1 bhejein, alag masla ho to 2.`,
    ur: (x: { n: number; id: string; d: number }) => `${x.n} ہمسائے پہلے ہی یہ مسئلہ رپورٹ کر چکے ہیں (${x.id}، ${x.d} دن سے زیرِ التوا)۔\nاپنی آواز شامل کرنے کے لیے 1 بھیجیں، الگ مسئلہ ہو تو 2۔`,
  },
  added: {
    en: (x: { id: string; n: number; url: string }) => `Done. ${x.id} now has ${x.n} residents behind it. Track it here: ${x.url}`,
    'ur-Latn': (x: { id: string; n: number; url: string }) => `Ho gaya. Ab ${x.id} ke peeche ${x.n} rehaishi hain. Yahan track karein: ${x.url}`,
    ur: (x: { id: string; n: number; url: string }) => `ہو گیا۔ اب ${x.id} کے پیچھے ${x.n} رہائشی ہیں۔ یہاں ٹریک کریں: ${x.url}`,
  },
  alreadyAdded: {
    en: (x: { id: string }) => `You've already added your voice to ${x.id}. I'll keep you updated.`,
    'ur-Latn': (x: { id: string }) => `Aap ${x.id} par pehle hi apni awaaz shamil kar chuke hain. Main aap ko update karta rahunga.`,
    ur: (x: { id: string }) => `آپ ${x.id} پر پہلے ہی اپنی آواز شامل کر چکے ہیں۔ میں آپ کو اپ ڈیٹ کرتا رہوں گا۔`,
  },
  assisted: {
    en: (x: { target: string }) => `This department has no online filing, so here is the complaint ready to submit to ${x.target}:`,
    'ur-Latn': (x: { target: string }) => `Is idare ki online filing nahi hai, is liye ${x.target} ko jama karwane ke liye tayyar shikayat yeh hai:`,
    ur: (x: { target: string }) => `اس ادارے کی آن لائن فائلنگ نہیں ہے، اس لیے ${x.target} کو جمع کروانے کے لیے تیار شکایت یہ ہے:`,
  },
  checkin: {
    en: (x: { id: string }) => `Is ${x.id} fixed yet? Reply 1 for yes, 2 for no.`,
    'ur-Latn': (x: { id: string }) => `Kya ${x.id} ka masla hal ho gaya? Haan ke liye 1, nahi ke liye 2 bhejein.`,
    ur: (x: { id: string }) => `کیا ${x.id} کا مسئلہ حل ہو گیا؟ ہاں کے لیے 1، نہیں کے لیے 2 بھیجیں۔`,
  },
  reminder: {
    en: (x: { id: string }) => `Reminder: is ${x.id} fixed? Reply 1 for yes, 2 for no. I won't escalate anything without your answer.`,
    'ur-Latn': (x: { id: string }) => `Yaad dihani: kya ${x.id} hal ho gaya? 1 = haan, 2 = nahi. Aap ke jawab ke baghair main kuch aage nahi bhejunga.`,
    ur: (x: { id: string }) => `یاد دہانی: کیا ${x.id} حل ہو گیا؟ 1 = ہاں، 2 = نہیں۔ آپ کے جواب کے بغیر میں کچھ آگے نہیں بھیجوں گا۔`,
  },
  consent: {
    en: (x: { tier: number }) => x.tier === 3 ? 'Reply 1 to get the post to copy, or 2 for not now.' : 'Reply 1 to approve and send, or 2 for not now.',
    'ur-Latn': (x: { tier: number }) => x.tier === 3 ? 'Post copy karne ke liye 1, abhi nahi ke liye 2.' : 'Manzoori aur bhejne ke liye 1, abhi nahi ke liye 2.',
    ur: (x: { tier: number }) => x.tier === 3 ? 'پوسٹ کاپی کرنے کے لیے 1، ابھی نہیں کے لیے 2۔' : 'منظوری اور بھیجنے کے لیے 1، ابھی نہیں کے لیے 2۔',
  },
  sent: {
    en: (x: { tier: number; id: string }) => `Sent. Tier ${x.tier} is on record for ${x.id}. I'll check again in 7 days.`,
    'ur-Latn': (x: { tier: number; id: string }) => `Bhej diya gaya. ${x.id} par Tier ${x.tier} record ho gaya. 7 din baad dobara poochunga.`,
    ur: (x: { tier: number; id: string }) => `بھیج دیا گیا۔ ${x.id} پر ٹیئر ${x.tier} ریکارڈ ہو گیا۔ 7 دن بعد دوبارہ پوچھوں گا۔`,
  },
  postReady: {
    en: () => 'Here is your post. Awaaz never posts for you: copy it and share it wherever you choose.',
    'ur-Latn': () => 'Yeh aap ki post hai. Awaaz aap ki taraf se kabhi post nahi karta, copy karke jahan chahein share karein.',
    ur: () => 'یہ آپ کی پوسٹ ہے۔ آواز آپ کی طرف سے کبھی پوسٹ نہیں کرتا، کاپی کر کے جہاں چاہیں شیئر کریں۔',
  },
  declined: {
    en: () => 'Okay, nothing was sent. Reply "escalate" any time to continue.',
    'ur-Latn': () => 'Theek hai, kuch nahi bheja gaya. Jab chahein "escalate" likh kar aage barhein.',
    ur: () => 'ٹھیک ہے، کچھ نہیں بھیجا گیا۔ جب چاہیں "escalate" لکھ کر آگے بڑھیں۔',
  },
  finalTier: {
    en: (x: { id: string }) => `All three escalation steps are on record for ${x.id}. I'll keep tracking it and include it in the Neighborhood Report.`,
    'ur-Latn': (x: { id: string }) => `${x.id} par teeno escalation steps record ho chuke hain. Main track karta rahunga aur Neighborhood Report mein shamil karunga.`,
    ur: (x: { id: string }) => `${x.id} پر تینوں مراحل ریکارڈ ہو چکے ہیں۔ میں ٹریک کرتا رہوں گا اور محلے کی رپورٹ میں شامل کروں گا۔`,
  },
  confirmFix: {
    en: (x: { id: string; summary: string }) => `A resident says ${x.id} (${x.summary}) is fixed. Can you confirm? Reply 1 if fixed, 2 if it's still there. A photo helps.`,
    'ur-Latn': (x: { id: string; summary: string }) => `Ek rehaishi ke mutabiq ${x.id} (${x.summary}) hal ho gaya hai. Kya aap tasdeeq kar sakte hain? Hal ho gaya to 1, abhi bhi maujood hai to 2. Tasveer bhejein to behtar.`,
    ur: (x: { id: string; summary: string }) => `ایک رہائشی کے مطابق ${x.id} (${x.summary}) حل ہو گیا ہے۔ کیا آپ تصدیق کر سکتے ہیں؟ حل ہو گیا تو 1، ابھی بھی موجود ہے تو 2۔ تصویر بھیجیں تو بہتر۔`,
  },
  authFixed: {
    en: (x: { id: string; auth: string }) => `${x.auth} marked ${x.id} as fixed. Is it really fixed? Reply 1 for yes, 2 for no.`,
    'ur-Latn': (x: { id: string; auth: string }) => `${x.auth} ne ${x.id} ko hal shuda qarar diya hai. Kya waqai hal ho gaya? 1 = haan, 2 = nahi.`,
    ur: (x: { id: string; auth: string }) => `${x.auth} نے ${x.id} کو حل شدہ قرار دیا ہے۔ کیا واقعی حل ہو گیا؟ 1 = ہاں، 2 = نہیں۔`,
  },
  waitVerify: {
    en: () => "Thanks. I've asked a neighbor to confirm the fix.",
    'ur-Latn': () => 'Shukriya. Maine ek parosi se tasdeeq ke liye kaha hai.',
    ur: () => 'شکریہ۔ میں نے ایک ہمسائے سے تصدیق کے لیے کہا ہے۔',
  },
  resolved: {
    en: (x: { id: string; d: number }) => `${x.id} is confirmed fixed after ${x.d} days. Thank you for raising your voice.`,
    'ur-Latn': (x: { id: string; d: number }) => `${x.id} ${x.d} din baad hal ho gaya, tasdeeq ho chuki hai. Awaaz uthane ka shukriya.`,
    ur: (x: { id: string; d: number }) => `${x.id} ${x.d} دن بعد حل ہو گیا، تصدیق ہو چکی ہے۔ آواز اٹھانے کا شکریہ۔`,
  },
  stillThere: {
    en: (x: { id: string }) => `Noted. ${x.id} stays open and the department has been told it's still there.`,
    'ur-Latn': (x: { id: string }) => `Note kar liya. ${x.id} khula rahega aur idare ko bata diya gaya hai ke masla ab bhi maujood hai.`,
    ur: (x: { id: string }) => `نوٹ کر لیا۔ ${x.id} کھلا رہے گا اور ادارے کو بتا دیا گیا ہے کہ مسئلہ اب بھی موجود ہے۔`,
  },
  pickOne: {
    en: () => 'Please reply 1 or 2.',
    'ur-Latn': () => 'Barah-e-karam 1 ya 2 bhejein.',
    ur: () => 'براہِ کرم 1 یا 2 بھیجیں۔',
  },
  error: {
    en: () => 'Something went wrong on our side. Please try again in a minute.',
    'ur-Latn': () => 'Hamari taraf se koi masla aa gaya. Ek minute baad dobara koshish karein.',
    ur: () => 'ہماری طرف سے کوئی مسئلہ آ گیا۔ ایک منٹ بعد دوبارہ کوشش کریں۔',
  },
} satisfies Record<string, Msg>;

export type MsgKey = keyof typeof M;
export function t(lang: Language | string, key: MsgKey, x: Record<string, unknown> = {}): string {
  return (M[key] as Msg)[pick(lang)](x);
}

/** Interpret a 1/2 or yes/no reply in English, Roman Urdu or Urdu. */
export function yesNo(text: string): 'yes' | 'no' | null {
  const s = text.trim().toLowerCase();
  if (/^(1|yes|y|haan|han|ha|ji|jee|theek|ہاں|جی)\b/.test(s) || /^(1|ہاں|جی)/.test(s)) return 'yes';
  if (/^(2|no|n|nahi|nahin|nai|نہیں|نہ)\b/.test(s) || /^(2|نہیں)/.test(s)) return 'no';
  return null;
}
