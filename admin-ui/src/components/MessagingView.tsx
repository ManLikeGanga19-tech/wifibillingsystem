import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import {
  Megaphone, Send, Users, CheckCircle2, Clock, Loader2, AlertTriangle,
  MessageSquare, ArrowRight, X, Wallet,
} from 'lucide-react';
import { api, ApiCampaign, PlatformAccount } from '../api/client';
import { Badge, Btn, Panel, RefreshBtn, ViewHeader, fmtDateTime, toast } from './ui';

type Channel = 'sms' | 'whatsapp';
type Audience = 'all' | 'active' | 'expired';
const AUDIENCE_LABEL: Record<Audience, string> = { all: 'All', active: 'Active', expired: 'Expired' };

function segmentsFor(text: string): number {
  const len = text.length;
  if (len === 0) return 0;
  return len <= 160 ? 1 : Math.ceil(len / 153);
}

export default function MessagingView() {
  const [channel, setChannel] = useState<Channel>('sms');
  const [audience, setAudience] = useState<Audience>('all');
  const [name, setName] = useState('');
  const [body, setBody] = useState('');
  const [confirm, setConfirm] = useState(false);
  const [sending, setSending] = useState(false);

  const [campaigns, setCampaigns] = useState<ApiCampaign[] | null>(null);
  const [counts, setCounts] = useState<{ all: number; active: number; expired: number } | null>(null);
  const [account, setAccount] = useState<PlatformAccount | null>(null);
  const [gateway, setGateway] = useState<{ name: string; managed: boolean } | null | false>(null);
  const pollRef = useRef<number | undefined>(undefined);

  const loadCampaigns = useCallback(async () => {
    try {
      const r = await api.campaigns.list();
      setCampaigns(r.results);
    } catch {
      /* keep the last list */
    }
  }, []);

  useEffect(() => {
    loadCampaigns();
    api.account.get().then(setAccount).catch(() => {});
    api.messaging.providers('sms')
      .then((r) => {
        const active = r.providers.find((p) => p.active);
        setGateway(active ? { name: active.name, managed: active.managed } : false);
      })
      .catch(() => setGateway(false));
  }, [loadCampaigns]);

  // Real recipient counts per audience, refreshed when the channel changes.
  useEffect(() => {
    api.campaigns.audience(channel).then(setCounts).catch(() => setCounts(null));
  }, [channel]);

  // Poll for live delivery progress while any campaign is still sending.
  useEffect(() => {
    const anySending = (campaigns ?? []).some((c) => c.status === 'sending' || c.status === 'queued');
    window.clearInterval(pollRef.current);
    if (anySending) pollRef.current = window.setInterval(loadCampaigns, 4000);
    return () => window.clearInterval(pollRef.current);
  }, [campaigns, loadCampaigns]);

  const recipients = counts ? counts[audience] : null;
  const segs = segmentsFor(body);
  const isSms = channel === 'sms';
  const managed = gateway && gateway.managed;
  // Cost only has a credit meaning on the WIFI.OS managed SMS gateway; a BYO gateway or
  // WhatsApp is billed by the ISP's own provider, so we show reach, not a credit price.
  const cost = recipients != null ? recipients * Math.max(1, segs) : null;
  const credits = account?.sms_remaining ?? null;
  const insufficient = isSms && managed && cost != null && credits != null && cost > credits;
  const noGateway = gateway === false;

  const canSend =
    !!body.trim() && (recipients ?? 0) > 0 && !insufficient && !noGateway && !sending;

  const submit = async () => {
    setSending(true);
    try {
      await api.campaigns.create({
        name: name.trim() || `${channel.toUpperCase()} blast to ${AUDIENCE_LABEL[audience].toLowerCase()} customers`,
        channel,
        audience,
        body: body.trim(),
      });
      toast('success', `Campaign queued to ${recipients} customer${recipients === 1 ? '' : 's'}.`);
      setName('');
      setBody('');
      setConfirm(false);
      loadCampaigns();
      api.account.get().then(setAccount).catch(() => {});
    } catch (e) {
      toast('error', e instanceof Error ? e.message : 'Could not queue the campaign.');
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<Megaphone className="h-4.5 w-4.5" />}
        title="Campaigns"
        subtitle="Send bulk SMS or WhatsApp to your customers — reminders, offers, notices."
      >
        <RefreshBtn onClick={loadCampaigns} />
      </ViewHeader>

      {/* Gateway + credit banner — ties this to the communications module and shows what a
          send actually costs before it happens. */}
      <GatewayBanner gateway={gateway} channel={channel} credits={credits} />

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
        {/* Compose */}
        <div className="lg:col-span-2 space-y-4 self-start">
          <Panel title="Compose broadcast">
            <label className="text-xs font-bold font-mono uppercase text-[#141414]/60 block mb-1">Channel</label>
            <div className="flex border border-[#141414] mb-4">
              {(['sms', 'whatsapp'] as const).map((ch) => (
                <button
                  key={ch}
                  onClick={() => setChannel(ch)}
                  className={`flex-1 py-2 text-xs font-bold font-mono uppercase transition ${
                    channel === ch ? 'bg-[#141414] text-[#E4E3E0]' : 'bg-white hover:bg-[#f0efec]'
                  }`}
                >
                  {ch === 'sms' ? 'SMS' : 'WhatsApp'}
                </button>
              ))}
            </div>

            <label className="text-xs font-bold font-mono uppercase text-[#141414]/60 block mb-1">Send to</label>
            <select
              value={audience}
              onChange={(e) => setAudience(e.target.value as Audience)}
              className="w-full bg-white border border-[#141414] p-2 text-xs outline-none font-mono mb-4"
            >
              {(['all', 'active', 'expired'] as const).map((a) => (
                <option key={a} value={a}>
                  {AUDIENCE_LABEL[a]} customers{counts ? ` (${counts[a].toLocaleString()})` : ''}
                </option>
              ))}
            </select>

            <label className="text-xs font-bold font-mono uppercase text-[#141414]/60 block mb-1">Campaign name (optional)</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. June price update"
              className="w-full bg-white border border-[#141414] p-2 text-xs outline-none mb-4"
            />

            <label className="text-xs font-bold font-mono uppercase text-[#141414]/60 block mb-1">Message</label>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={5}
              maxLength={640}
              placeholder="Type your message to customers…"
              className="w-full bg-white border border-[#141414] p-2 text-xs outline-none leading-relaxed resize-y"
            />
            <div className="flex justify-between text-[11px] font-mono text-[#141414]/50 mt-1">
              <span>{body.length}/640</span>
              {isSms && <span className={segs > 1 ? 'text-[#B26B00]' : ''}>{segs} segment{segs === 1 ? '' : 's'} / customer</span>}
            </div>
          </Panel>

          {/* Cost + send */}
          <Panel>
            <div className="flex items-center justify-between text-xs mb-2">
              <span className="text-[#141414]/60">Recipients</span>
              <span className="font-mono font-bold">
                {recipients == null ? '—' : recipients.toLocaleString()}
              </span>
            </div>
            {isSms && managed && (
              <div className="flex items-center justify-between text-xs mb-2">
                <span className="text-[#141414]/60">Estimated cost</span>
                <span className={`font-mono font-bold ${insufficient ? 'text-[#B22222]' : ''}`}>
                  {cost == null ? '—' : `${cost.toLocaleString()} credits`}
                </span>
              </div>
            )}
            {insufficient && (
              <p className="text-[11px] text-[#B22222] flex items-center gap-1.5 mb-2">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                Not enough credits ({credits?.toLocaleString()} left). Top up in Wallet.
              </p>
            )}
            <Btn variant="green" onClick={() => setConfirm(true)} disabled={!canSend}>
              <Send className="h-3.5 w-3.5" />
              Review &amp; send
            </Btn>
          </Panel>
        </div>

        {/* History */}
        <div className="lg:col-span-3">
          <Panel title="Broadcast history">
            {campaigns === null ? (
              <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-[#141414]/40" /></div>
            ) : campaigns.length === 0 ? (
              <div className="py-10 text-center font-mono text-xs text-[#141414]/50">
                <Users className="h-6 w-6 mx-auto mb-2" />
                No broadcasts yet. Compose your first message on the left.
              </div>
            ) : (
              <ul className="divide-y divide-[#141414]/10 -mx-4 -mb-4">
                {campaigns.map((c) => (
                  <Fragment key={c.id}>
                    <CampaignRow c={c} />
                  </Fragment>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      </div>

      {confirm && recipients != null && (
        <ConfirmModal
          name={name.trim() || `${channel.toUpperCase()} blast`}
          channel={channel}
          audience={AUDIENCE_LABEL[audience]}
          recipients={recipients}
          cost={isSms && managed ? cost : null}
          credits={credits}
          sending={sending}
          onCancel={() => setConfirm(false)}
          onConfirm={submit}
        />
      )}
    </div>
  );
}

function GatewayBanner({
  gateway, channel, credits,
}: {
  gateway: { name: string; managed: boolean } | null | false;
  channel: Channel;
  credits: number | null;
}) {
  if (gateway === null) return null; // loading
  if (gateway === false) {
    return (
      <a href="#/settings/sms" className="flex items-center gap-2.5 border border-[#B26B00] bg-[#FFF8EC] px-3 py-2.5 text-xs hover:bg-[#FFF3DC] transition">
        <AlertTriangle className="h-4 w-4 text-[#B26B00] shrink-0" />
        <span className="flex-1 text-[#141414]/75">
          <b className="text-[#B26B00]">No SMS gateway is active.</b> Campaigns won&apos;t send until you set one up in Communications → SMS.
        </span>
        <span className="inline-flex items-center gap-1 font-mono uppercase text-[10px] text-[#B26B00] font-bold shrink-0">Set up <ArrowRight className="h-3 w-3" /></span>
      </a>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border border-[#141414]/15 bg-[#f4f4f2] px-3 py-2.5 text-xs">
      <span className="inline-flex items-center gap-1.5 text-[#141414]/70">
        <MessageSquare className="h-4 w-4 text-[#228B22]" /> Sending on <b>{gateway.name}</b>
      </span>
      {channel === 'sms' && gateway.managed && credits != null && (
        <span className="inline-flex items-center gap-1.5 text-[#141414]/70">
          <Wallet className="h-3.5 w-3.5" /> {credits.toLocaleString()} SMS credits
        </span>
      )}
      {channel === 'whatsapp' && (
        <span className="text-[#B26B00]">WhatsApp bulk needs an approved template for customers you haven&apos;t messaged in 24h.</span>
      )}
      <a href="#/settings/sms" className="ml-auto inline-flex items-center gap-1 font-mono uppercase text-[10px] text-[#141414]/50 shrink-0">
        Comms settings <ArrowRight className="h-3 w-3" />
      </a>
    </div>
  );
}

function CampaignRow({ c }: { c: ApiCampaign }) {
  const done = c.status === 'done';
  const progress = c.total_recipients ? Math.round(100 * (c.sent_count + c.failed_count) / c.total_recipients) : 0;
  return (
    <li className="px-4 py-3 space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <span className="font-bold font-mono text-xs uppercase truncate">{c.name}</span>
        <Badge color={done ? 'green' : c.status === 'sending' ? 'blue' : 'gray'}>
          {done ? <CheckCircle2 className="h-3 w-3" /> : c.status === 'sending' ? <Loader2 className="h-3 w-3 animate-spin" /> : <Clock className="h-3 w-3" />}
          <span className="ml-1">{c.status}</span>
        </Badge>
      </div>
      <p className="text-xs text-[#141414]/80 leading-relaxed line-clamp-2">{c.body}</p>
      {!done && c.status === 'sending' && (
        <div className="h-1 bg-[#141414]/10 overflow-hidden">
          <div className="h-full bg-[#228B22] transition-all" style={{ width: `${progress}%` }} />
        </div>
      )}
      <p className="text-[11px] font-mono text-[#141414]/55 flex flex-wrap gap-x-2">
        <span className="uppercase">{c.channel}</span> ·
        <span>{c.audience}</span> ·
        <span className="text-[#228B22]">{c.sent_count.toLocaleString()} sent</span>
        {c.failed_count > 0 && <span className="text-[#B22222]">· {c.failed_count} failed</span>}
        <span>· of {c.total_recipients.toLocaleString()}</span>
        <span>· {fmtDateTime(c.created_at)}</span>
      </p>
    </li>
  );
}

function ConfirmModal({
  name, channel, audience, recipients, cost, credits, sending, onCancel, onConfirm,
}: {
  name: string; channel: Channel; audience: string; recipients: number;
  cost: number | null; credits: number | null; sending: boolean;
  onCancel: () => void; onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 bg-[#141414]/70 flex items-center justify-center p-4" onClick={onCancel}>
      <div className="bg-white border border-[#141414] max-w-sm w-full p-5" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 mb-3">
          <Send className="h-4 w-4" />
          <h3 className="font-bold font-mono uppercase text-sm">Send this campaign?</h3>
        </div>
        <p className="text-sm text-[#141414]/75 leading-relaxed">
          <b>{name}</b> will be sent to <b>{recipients.toLocaleString()}</b> {audience.toLowerCase()} customer{recipients === 1 ? '' : 's'} on <b>{channel.toUpperCase()}</b>.
        </p>
        {cost != null && (
          <p className="text-sm text-[#141414]/75 mt-2">
            Estimated cost: <b>{cost.toLocaleString()} credits</b>
            {credits != null && <span className="text-[#141414]/50"> (you have {credits.toLocaleString()})</span>}.
          </p>
        )}
        <p className="text-[11px] text-[#B26B00] mt-2">This can&apos;t be undone once it starts sending.</p>
        <div className="flex items-center gap-2 mt-4">
          <Btn variant="green" onClick={onConfirm} disabled={sending}>
            {sending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
            Send now
          </Btn>
          <Btn variant="outline" onClick={onCancel} disabled={sending}>
            <X className="h-3.5 w-3.5" /> Cancel
          </Btn>
        </div>
      </div>
    </div>
  );
}
