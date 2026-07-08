import React, { useState } from 'react';
import { Invoice, Subscriber, BandwidthProfile } from '../types';
import { 
  FileText, 
  Search, 
  CheckCircle, 
  AlertTriangle, 
  Clock, 
  CreditCard, 
  Printer, 
  X, 
  Check, 
  ArrowUpRight, 
  Info,
  ChevronRight,
  TrendingUp,
  Receipt,
  Download
} from 'lucide-react';

interface InvoiceListProps {
  invoices: Invoice[];
  subscribers: Subscriber[];
  onPayInvoice: (invoiceId: string) => void;
  onAddLog: (category: 'Router' | 'Billing' | 'Subscriber' | 'Hotspot', type: 'info' | 'success' | 'warning' | 'error', message: string) => void;
  simulatedDate: string;
}

export default function InvoiceList({
  invoices,
  subscribers,
  onPayInvoice,
  onAddLog,
  simulatedDate
}: InvoiceListProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'Paid' | 'Unpaid' | 'Overdue'>('all');
  const [selectedInvoice, setSelectedInvoice] = useState<Invoice | null>(null);
  const [selectedInvoiceIds, setSelectedInvoiceIds] = useState<string[]>([]);

  const handlePaySubmit = (inv: Invoice) => {
    onPayInvoice(inv.id);
    onAddLog(
      'Billing',
      'success',
      `Payment Resolved: Settle Invoice ${inv.invoiceNumber} of Ksh ${inv.amount.toLocaleString()} for ${inv.subscriberName}.`
    );
    
    // Simulating Router dynamic restore
    const linkedSub = subscribers.find(s => s.id === inv.subscriberId);
    if (linkedSub) {
      onAddLog(
        'Router',
        'success',
        `MikroTik sync: Restored bypass active state on firewall src-address=${linkedSub.ipAddress} following invoice clearance.`
      );
    }
    
    // update modal view
    setSelectedInvoice(prev => prev && prev.id === inv.id ? { ...prev, status: 'Paid', datePaid: simulatedDate } : prev);
  };

  // Filter logic
  const filteredInvoices = invoices.filter(inv => {
    const matchesSearch = 
      inv.invoiceNumber.toLowerCase().includes(searchQuery.toLowerCase()) ||
      inv.subscriberName.toLowerCase().includes(searchQuery.toLowerCase()) ||
      inv.planName.toLowerCase().includes(searchQuery.toLowerCase());

    const matchesStatus = statusFilter === 'all' || inv.status === statusFilter;

    return matchesSearch && matchesStatus;
  });

  return (
    <div className="space-y-6 text-[#141414]">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-sm font-serif italic font-bold text-[#141414] flex items-center gap-2 uppercase">
            <Receipt className="h-4.5 w-4.5" />
            <span>Subscriber Invoices & Transactions Ledger</span>
          </h2>
          <p className="text-xs font-mono text-[#141414]/70 mt-0.5">
            Overview of automatically dispatched billing statements. Settle pending dues to immediately unlock bandwidth limits inside the active RouterOS queue.
          </p>
        </div>
      </div>

      {/* Invoice Filter & Search */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 bg-white border border-[#141414] p-3 rounded-none">
        {/* Search */}
        <div className="flex items-center gap-2 px-3 border border-[#141414] bg-white rounded-none">
          <Search className="h-4 w-4 text-[#141414]/50" />
          <input
            type="text"
            placeholder="Filter invoice number, client, speed tier..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-transparent outline-none py-2 text-xs font-mono text-[#141414] placeholder-[#141414]/40"
          />
        </div>

        {/* Status */}
        <div className="flex items-center gap-2 font-mono text-xs">
          <label className="text-[#141414]/60 font-bold uppercase shrink-0">FILTER:</label>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as any)}
            className="w-full bg-white border border-[#141414] p-1.5 text-xs font-mono text-[#141414] rounded-none outline-none"
          >
            <option value="all">ALL_INVOICES</option>
            <option value="Paid">PAID_RECOLLECT</option>
            <option value="Unpaid">UNPAID_GRACE</option>
            <option value="Overdue">OVERDUE_SUSPENDED</option>
          </select>
        </div>

        {/* Count overview */}
        <div className="flex items-center justify-end font-mono text-xs text-[#141414]/60 uppercase tracking-tight pr-2">
          Total: {filteredInvoices.length} registers found
        </div>
      </div>

      {/* Batch invoice actions */}
      {selectedInvoiceIds.length > 0 && (
        <div className="bg-[#E4E3E0] border border-[#141414] p-3 text-xs font-mono flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-[#141414] animate-fade-in mb-4">
          <div className="flex items-center gap-2">
            <span className="bg-[#141414] text-white px-2 py-0.5 text-[11px] font-bold uppercase">Batch Invoice Options</span>
            <span className="font-bold">{selectedInvoiceIds.length} invoice(s) selected</span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => {
                selectedInvoiceIds.forEach(id => {
                  const inv = invoices.find(i => i.id === id);
                  if (inv && inv.status !== 'Paid') {
                    onPayInvoice(inv.id);
                  }
                });
                onAddLog('Billing', 'success', `Batch Action: Mark ${selectedInvoiceIds.length} invoices as settled.`);
                setSelectedInvoiceIds([]);
              }}
              className="bg-[#228B22] text-white border border-[#228B22] px-3 py-1 text-[11px] font-bold uppercase transition hover:bg-white hover:text-[#228B22] cursor-pointer"
            >
              Batch Settle [PAY]
            </button>
            <button
              onClick={() => {
                selectedInvoiceIds.forEach(id => {
                  const inv = invoices.find(i => i.id === id);
                  if (inv) {
                    onAddLog('Billing', 'info', `Reminder Dispatched: Automated billing notification SMS & email queued for ${inv.subscriberName} regarding ${inv.invoiceNumber}.`);
                  }
                });
                alert(`Broadcasted billing reminders for ${selectedInvoiceIds.length} selected subscriber accounts.`);
                setSelectedInvoiceIds([]);
              }}
              className="bg-[#141414] text-white border border-[#141414] px-3 py-1 text-[11px] font-bold uppercase transition hover:bg-white hover:text-[#141414] cursor-pointer"
            >
              Dispatch Reminders
            </button>
            <button
              onClick={() => setSelectedInvoiceIds([])}
              className="text-[#141414]/65 hover:text-[#141414] px-2 text-[11px] font-bold uppercase cursor-pointer"
            >
              Clear
            </button>
          </div>
        </div>
      )}

      {/* Invoices List Table */}
      <div className="bg-white border border-[#141414] rounded-none overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse font-mono text-xs">
            <thead>
              <tr className="bg-[#E4E3E0] border-b border-[#141414] text-[#141414] text-[11px] font-mono font-bold uppercase tracking-wider">
                <th className="py-2.5 px-3 font-bold w-10">
                  <input
                    type="checkbox"
                    checked={filteredInvoices.length > 0 && selectedInvoiceIds.length === filteredInvoices.length}
                    onChange={(e) => {
                      if (e.target.checked) {
                        setSelectedInvoiceIds(filteredInvoices.map(i => i.id));
                      } else {
                        setSelectedInvoiceIds([]);
                      }
                    }}
                    className="cursor-pointer accent-[#141414] h-3.5 w-3.5 block"
                  />
                </th>
                <th className="py-2.5 px-3 font-bold">INV_NUMBER</th>
                <th className="py-2.5 px-3 font-bold">SUBSCRIBER_DETAILS</th>
                <th className="py-2.5 px-3 font-bold">SERVICE_TIER</th>
                <th className="py-2.5 px-3 font-bold">TIMELINE_DUE</th>
                <th className="py-2.5 px-3 font-bold">STATUS</th>
                <th className="py-2.5 px-3 font-bold">TOTAL_DUE</th>
                <th className="py-2.5 px-3 font-bold text-right">OPERATIONS</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#141414]/15">
              {filteredInvoices.slice().reverse().map((inv) => {
                const sub = subscribers.find(s => s.id === inv.subscriberId);
                const isSelected = selectedInvoiceIds.includes(inv.id);
                return (
                  <tr key={inv.id} className={`hover:bg-[#f0efec]/40 transition text-[11px] text-[#141414] ${isSelected ? 'bg-[#f0efec]' : ''}`}>
                    <td className="py-2.5 px-3">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setSelectedInvoiceIds(prev => [...prev, inv.id]);
                          } else {
                            setSelectedInvoiceIds(prev => prev.filter(id => id !== inv.id));
                          }
                        }}
                        className="cursor-pointer accent-[#141414] h-3.5 w-3.5 block"
                      />
                    </td>
                    {/* Invoice ID */}
                    <td className="py-2.5 px-3 font-bold">
                      {inv.invoiceNumber}
                    </td>

                    {/* Subscriber */}
                    <td className="py-2.5 px-3">
                      <div className="font-bold underline text-[#141414]">{inv.subscriberName}</div>
                      {sub && (
                        <div className="text-[11px] text-[#141414]/60 mt-0.5">
                          IP: {sub.ipAddress} â€¢ {sub.phone}
                        </div>
                      )}
                    </td>

                    {/* Plan */}
                    <td className="py-2.5 px-3 font-bold text-[#141414]">
                      {inv.planName}
                    </td>

                    {/* Timeline */}
                    <td className="py-2.5 px-3 text-[#141414]/75">
                      <div>ISSUED: <span className="font-mono text-xs font-bold">{inv.dateCreated}</span></div>
                      <div className="text-xs mt-0.5">DEADLINE: <span className="font-mono text-xs">{inv.dateDue}</span></div>
                    </td>

                    {/* Status */}
                    <td className="py-2.5 px-3">
                      <span className={`inline-flex items-center gap-1.5 px-1.5 py-0.2 border text-[11px] font-bold uppercase rounded-none ${
                        inv.status === 'Paid' ? 'bg-[#228B22]/10 border-[#228B22] text-[#228B22]' :
                        inv.status === 'Overdue' ? 'bg-[#FF4500]/10 border-[#FF4500] text-[#FF4500]' :
                        'bg-white border-[#141414] text-[#141414]'
                      }`}>
                        <span className={`w-1/5 h-1 ${
                          inv.status === 'Paid' ? 'bg-[#228B22]' :
                          inv.status === 'Overdue' ? 'bg-[#FF4500]' :
                          'bg-[#141414]'
                        }`}></span>
                        {inv.status}
                      </span>
                    </td>

                    {/* Amount */}
                    <td className="py-2.5 px-3 font-bold text-[#141414] text-[12px]">
                      Ksh {inv.amount.toLocaleString()}
                    </td>

                    {/* Action buttons */}
                    <td className="py-2.5 px-3 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <button
                          type="button"
                          onClick={() => setSelectedInvoice(inv)}
                          className="px-2 py-1 text-[11px] font-mono font-bold uppercase border border-[#141414] hover:bg-[#E4E3E0] rounded-none transition cursor-pointer text-[#141414]"
                        >
                          View Bill
                        </button>

                        {inv.status !== 'Paid' && (
                          <button
                            type="button"
                            onClick={() => handlePaySubmit(inv)}
                            className="bg-[#228B22] hover:bg-white hover:text-[#228B22] border border-[#228B22] text-white font-bold font-mono text-[11px] px-2 py-1 rounded-none transition inline-flex items-center gap-1 cursor-pointer"
                            title="Collect manual payment"
                          >
                            <CreditCard className="h-3 w-3" />
                            Pay
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Invoice Detail Printable Popup modal */}
      {selectedInvoice && (
        <div id="invoice-receipt-modal" className="fixed inset-0 bg-[#141414]/65 flex items-center justify-center p-4 z-50 animate-fade-in">
          <div className="bg-white border-2 border-[#141414] rounded-none w-full max-w-xl overflow-hidden relative shadow-none">
            {/* Header toolbar */}
            <div className="flex items-center justify-between px-4 py-2 border-b border-[#141414] bg-[#E4E3E0]">
              <span className="text-xs font-mono font-bold text-[#141414] uppercase">BILL RECEIPT DIALOG</span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => window.print()}
                  className="p-1 px-2.5 bg-white text-[#141414] border border-[#141414]/40 hover:bg-[#f0efec] rounded-none text-[11px] font-mono font-bold flex items-center gap-1 transition cursor-pointer"
                >
                  <Printer className="h-3 w-3" />
                  Print
                </button>
                <button 
                  onClick={() => setSelectedInvoice(null)}
                  className="p-1 border border-[#141414]/30 bg-white hover:bg-[#141414] hover:text-white rounded-none transition cursor-pointer"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>

            {/* Printable Area content */}
            <div className="p-5 space-y-5 bg-white text-[#141414] font-mono border border-[#141414] m-4 text-xs">
              
              {/* Receipt ISP Header */}
              <div className="flex justify-between items-start">
                <div>
                  <h3 className="text-xs font-serif italic font-bold uppercase tracking-tight text-[#141414]">
                    Wireless Business ISP Node
                  </h3>
                  <div className="text-[11px] text-[#141414]/75 mt-1 font-mono leading-tight">
                    100 Loop Highway, CyberCenter Complex<br />
                    Billing Help: billing@fastwifi.net<br />
                    Tel: +254 700 111 222
                  </div>
                </div>

                <div className="text-right">
                  <h2 className="text-xs font-bold text-[#141414] uppercase tracking-wide">
                    STATEMENT_EXP_RECEIPT
                  </h2>
                  <div className="text-[11px] text-[#141414]/75 mt-1 leading-tight">
                    Invoice No: <span className="font-bold text-[#141414] underline">{selectedInvoice.invoiceNumber}</span><br />
                    Date Issued: {selectedInvoice.dateCreated}<br />
                    Date Due: {selectedInvoice.dateDue}
                  </div>
                </div>
              </div>

              <hr className="border-[#141414]/20- my-1" />

              {/* Bill To Info */}
              <div className="grid grid-cols-2 gap-4 text-xs">
                <div>
                  <span className="text-[10px] font-bold text-[#141414]/60 block uppercase">CLIENT PROFILE:</span>
                  <div className="font-bold text-[#141414] mt-1">{selectedInvoice.subscriberName}</div>
                  {subscribers.find(s => s.id === selectedInvoice.subscriberId) && (
                    <div className="text-[#141414]/75 leading-tight mt-0.5 space-y-0.5">
                      <div>Phone: {subscribers.find(s => s.id === selectedInvoice.subscriberId)?.phone}</div>
                      <div>Room: {subscribers.find(s => s.id === selectedInvoice.subscriberId)?.address || 'N/A'}</div>
                      <div>Static IP Binding: {subscribers.find(s => s.id === selectedInvoice.subscriberId)?.ipAddress}</div>
                    </div>
                  )}
                </div>

                <div className="text-right">
                  <span className="text-[10px] font-bold text-[#141414]/60 block uppercase">BILLING PERIOD:</span>
                  <div className="font-bold text-[#141414] mt-1">
                    {selectedInvoice.periodStart} / {selectedInvoice.periodEnd}
                  </div>
                  <div className="text-[#141414]/75 mt-1">
                    Status: <span className={`font-bold uppercase ${selectedInvoice.status === 'Paid' ? 'text-[#228B22]' : 'text-[#FF4500]'}`}>{selectedInvoice.status}</span>
                  </div>
                  {selectedInvoice.status === 'Paid' && selectedInvoice.datePaid && (
                    <div className="text-[11px] text-[#141414]/60 mt-0.5">
                      Paid On: {selectedInvoice.datePaid}
                    </div>
                  )}
                </div>
              </div>

              {/* Items Table */}
              <div className="border border-[#141414] rounded-none overflow-hidden">
                <table className="w-full text-left text-[11px] bg-white font-mono">
                  <thead>
                    <tr className="bg-[#f0efec] border-b border-[#141414] text-[#141414] font-bold">
                      <th className="py-2 px-3">Service & Queue Limit Description</th>
                      <th className="py-2 px-3 text-right">Cycle Days</th>
                      <th className="py-2 px-3 text-right">Unit Price</th>
                      <th className="py-2 px-3 text-right">Total Price</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#141414] text-[#141414]/90">
                    <tr>
                      <td className="py-3 px-3">
                        <span className="font-bold block text-[#141414]">{selectedInvoice.planName} Package</span>
                        <div className="text-[11px] text-[#141414]/60">Automated IP pool allocation control</div>
                      </td>
                      <td className="py-3 px-3 text-right font-bold">Cycle Item</td>
                      <td className="py-3 px-3 text-right">Ksh {selectedInvoice.amount.toLocaleString()}</td>
                      <td className="py-3 px-3 text-right font-bold">Ksh {selectedInvoice.amount.toLocaleString()}</td>
                    </tr>
                    {/* Tax row */}
                    <tr className="bg-[#f0efec]/40">
                      <td colSpan={3} className="py-2 px-3 text-right font-bold text-[#141414]/60">Service Fee Tax (0.0%)</td>
                      <td className="py-2 px-3 text-right">Ksh 0</td>
                    </tr>
                    <tr className="bg-[#f0efec]">
                      <td colSpan={3} className="py-2 px-3 text-right font-bold text-[#141414]">Grand Total Due:</td>
                      <td className="py-2 px-3 text-right font-bold text-[#141414]">Ksh {selectedInvoice.amount.toLocaleString()}</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {/* Footer Terms */}
              <div className="text-[11px] text-[#141414]/60 leading-relaxed text-center space-y-0.5 border-t border-[#141414]/20 pt-2 font-mono">
                <div>* Billing Policy: Accounts must be settled within the grace period to avoid router bandwidth cutoff.</div>
                <div>All queue shapes are dynamically triggered from active MikroTik billing sync upon payment validation.</div>
              </div>

            </div>

            {/* Bottom pay button when unpaid */}
            {selectedInvoice.status !== 'Paid' && (
              <div className="px-4 py-3 border-t border-[#141414] bg-[#f0efec] flex gap-2">
                <button
                  type="button"
                  onClick={() => handlePaySubmit(selectedInvoice)}
                  className="w-full bg-[#228B22] hover:bg-white hover:text-[#228B22] border border-[#228B22] text-white font-bold py-2 text-center text-xs font-mono uppercase rounded-none transition cursor-pointer"
                >
                  Settle Bill & Active Line Immediately (Ksh {selectedInvoice.amount.toLocaleString()})
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
