import React, { useMemo, useState } from 'react';
import { MessageSquare, Send, Smartphone, Users, CheckCircle2, Clock } from 'lucide-react';
import { Subscriber, OutboundCampaign } from '../types';

interface MessagingViewProps {
  campaigns: OutboundCampaign[];
  subscribers: Subscriber[];
  onSendCampaign: (campaign: Omit<OutboundCampaign, 'id' | 'sentAt' | 'status'>) => void;
  onAddLog: (
    category: 'Router' | 'Billing' | 'Subscriber' | 'Hotspot',
    type: 'info' | 'success' | 'warning' | 'error',
    message: string
  ) => void;
}

const TEMPLATES = [
  { label: 'Payment reminder', body: 'Habari! Your WiFi subscription is due. Lipa na M-Pesa Paybill to stay connected. Thank you!' },
  { label: 'New offer', body: 'Great news! New weekly plan now available at KSh 350 - faster speeds, 7 days unlimited. Dial in via the portal today.' },
  { label: 'Maintenance notice', body: 'Notice: brief network maintenance tonight 11PM-1AM. Service may be interrupted. We apologize for any inconvenience.' },
];

export default function MessagingView({ campaigns, subscribers, onSendCampaign, onAddLog }: MessagingViewProps) {
  const [channel, setChannel] = useState<'SMS' | 'WhatsApp'>('SMS');
  const [audience, setAudience] = useState<'All' | 'Active' | 'Expired'>('All');
  const [name, setName] = useState('');
  const [body, setBody] = useState('');

  const audienceCounts = useMemo(() => ({
    All: subscribers.length,
    Active: subscribers.filter(s => s.status === 'Active').length,
    Expired: subscribers.filter(s => s.status === 'Expired').length,
  }), [subscribers]);

  const recipients = audienceCounts[audience];
  const smsSegments = Math.max(1, Math.ceil(body.length / 160));
  const totalDelivered = campaigns.reduce((acc, c) => acc + c.recipients, 0);

  const handleSend = (e: React.FormEvent) => {
    e.preventDefault();
    if (!body.trim() || recipients === 0) {
      onAddLog('Subscriber', 'warning', 'Messaging: Send blocked - empty message or zero recipients in selected audience.');
      return;
    }
    onSendCampaign({
      name: name.trim() || `${channel} blast to ${audience.toLowerCase()} clients`,
      channel,
      audience,
      body: body.trim(),
      recipients,
    });
    setName('');
    setBody('');
  };

  return (
    <div className="space-y-6 text-[#141414]">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-sm font-serif italic font-bold text-[#141414] flex items-center gap-2 uppercase">
            <MessageSquare className="h-4.5 w-4.5" />
            <span>Client Messaging</span>
          </h2>
          <p className="text-xs font-mono text-[#141414]/70 mt-0.5">
            Send bulk SMS or WhatsApp messages to your clients: payment reminders, offers, and maintenance notices.
          </p>
        </div>
      </div>

      {/* Stat tiles */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white border border-[#141414] p-4">
          <p className="text-[11px] font-mono opacity-60 uppercase">Campaigns Sent</p>
          <p className="text-xl font-black font-mono mt-1">{campaigns.length}</p>
        </div>
        <div className="bg-white border border-[#141414] p-4">
          <p className="text-[11px] font-mono opacity-60 uppercase">Messages Delivered</p>
          <p className="text-xl font-black font-mono mt-1 text-[#228B22]">{totalDelivered.toLocaleString()}</p>
        </div>
        <div className="bg-white border border-[#141414] p-4">
          <p className="text-[11px] font-mono opacity-60 uppercase">Reachable Clients</p>
          <p className="text-xl font-black font-mono mt-1">{audienceCounts.All}</p>
        </div>
        <div className="bg-white border border-[#141414] p-4">
          <p className="text-[11px] font-mono opacity-60 uppercase">Active Right Now</p>
          <p className="text-xl font-black font-mono mt-1">{audienceCounts.Active}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Compose panel */}
        <form onSubmit={handleSend} className="lg:col-span-2 bg-white border border-[#141414] p-5 space-y-4 self-start">
          <h3 className="text-xs font-bold font-mono uppercase tracking-wide border-b border-[#141414]/20 pb-2">
            Compose Broadcast
          </h3>

          {/* Channel toggle */}
          <div className="space-y-1">
            <label className="text-xs font-bold text-[#141414]/60 uppercase block">Channel</label>
            <div className="flex border border-[#141414]">
              {(['SMS', 'WhatsApp'] as const).map(ch => (
                <button
                  key={ch}
                  type="button"
                  onClick={() => setChannel(ch)}
                  className={`flex-1 py-2 text-xs font-bold font-mono uppercase flex items-center justify-center gap-1.5 transition cursor-pointer ${
                    channel === ch ? 'bg-[#141414] text-[#E4E3E0]' : 'bg-white text-[#141414] hover:bg-[#f0efec]'
                  }`}
                >
                  <Smartphone className="h-3.5 w-3.5" />
                  {ch}
                </button>
              ))}
            </div>
            {channel === 'WhatsApp' && (
              <p className="text-[11px] font-mono text-[#FF4500] mt-1">
                Note: WhatsApp bulk messages to clients you haven't chatted with in 24h require an approved template.
              </p>
            )}
          </div>

          {/* Audience */}
          <div className="space-y-1">
            <label className="text-xs font-bold text-[#141414]/60 uppercase block">Send To</label>
            <select
              value={audience}
              onChange={(e) => setAudience(e.target.value as typeof audience)}
              className="w-full bg-white border border-[#141414] p-2 text-xs rounded-none outline-none font-mono"
            >
              <option value="All">All clients ({audienceCounts.All})</option>
              <option value="Active">Active clients ({audienceCounts.Active})</option>
              <option value="Expired">Expired clients ({audienceCounts.Expired})</option>
            </select>
          </div>

          {/* Campaign name */}
          <div className="space-y-1">
            <label className="text-xs font-bold text-[#141414]/60 uppercase block">Campaign Name (optional)</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. June price update"
              className="w-full bg-white border border-[#141414] p-2 text-xs rounded-none outline-none"
            />
          </div>

          {/* Message body */}
          <div className="space-y-1">
            <label className="text-xs font-bold text-[#141414]/60 uppercase block">Message</label>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={5}
              maxLength={480}
              placeholder="Type your message to clients..."
              className="w-full bg-white border border-[#141414] p-2 text-xs rounded-none outline-none leading-relaxed"
            />
            <div className="flex justify-between text-[11px] font-mono opacity-60">
              <span>{body.length}/480 characters</span>
              {channel === 'SMS' && <span>{smsSegments} SMS segment{smsSegments > 1 ? 's' : ''} per client</span>}
            </div>
          </div>

          {/* Quick templates */}
          <div className="space-y-1">
            <label className="text-xs font-bold text-[#141414]/60 uppercase block">Quick Templates</label>
            <div className="flex flex-wrap gap-1.5">
              {TEMPLATES.map(t => (
                <button
                  key={t.label}
                  type="button"
                  onClick={() => setBody(t.body)}
                  className="px-2 py-1 border border-[#141414]/40 text-[11px] font-mono hover:bg-[#141414] hover:text-white transition cursor-pointer"
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>

          <button
            type="submit"
            className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-2.5 text-xs font-bold font-mono text-white bg-[#141414] hover:bg-[#228B22] border border-[#141414] rounded-none transition cursor-pointer uppercase"
          >
            <Send className="h-4 w-4" />
            Send to {recipients} client{recipients !== 1 ? 's' : ''}
          </button>
        </form>

        {/* History */}
        <div className="lg:col-span-3 bg-white border border-[#141414]">
          <div className="p-4 border-b border-[#141414]/20 flex items-center justify-between">
            <h3 className="text-xs font-bold font-mono uppercase tracking-wide">Broadcast History</h3>
            <span className="text-[11px] font-mono opacity-60">{campaigns.length} campaigns</span>
          </div>
          {campaigns.length === 0 ? (
            <div className="p-10 text-center font-mono text-xs opacity-50">
              <Users className="h-6 w-6 mx-auto mb-2" />
              No broadcasts sent yet. Compose your first message on the left.
            </div>
          ) : (
            <ul className="divide-y divide-[#141414]/10 max-h-[32rem] overflow-y-auto">
              {[...campaigns].reverse().map(c => (
                <li key={c.id} className="p-4 space-y-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-bold font-mono text-xs uppercase truncate">{c.name}</span>
                    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 border text-[11px] font-bold font-mono uppercase shrink-0 ${
                      c.status === 'Sent'
                        ? 'text-[#228B22] border-[#228B22]/40 bg-[#228B22]/5'
                        : 'text-[#141414]/60 border-[#141414]/30'
                    }`}>
                      {c.status === 'Sent' ? <CheckCircle2 className="h-3 w-3" /> : <Clock className="h-3 w-3" />}
                      {c.status}
                    </span>
                  </div>
                  <p className="text-xs text-[#141414]/80 leading-relaxed">{c.body}</p>
                  <p className="text-[11px] font-mono opacity-60">
                    {c.channel} • {c.audience} clients • {c.recipients} recipients • {c.sentAt}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
