// @ts-check
import starlight from '@astrojs/starlight';
import { defineConfig } from 'astro/config';

/**
 * docs.wifios.co.ke — the WIFI.OS usage manual.
 *
 * Starlight (static Astro) because documentation is content, not an app: it ships as plain
 * HTML with built-in search, so it's fast on a Kenyan mobile network and has no API to talk
 * to. Served behind the edge Caddy exactly like the marketing site.
 */
export default defineConfig({
  site: 'https://docs.wifios.co.ke',
  server: {
    // Dev only: reachable at http://docs:4700 on the docker network.
    host: true,
    allowedHosts: ['docs', 'localhost', '127.0.0.1'],
  },
  integrations: [
    starlight({
      title: 'WIFI.OS Docs',
      description: 'How to run your ISP on WIFI.OS — hotspot, PPPoE, billing and more.',
      tagline: 'The billing system for Kenyan WISPs.',
      credits: false,
      pagination: true,
      // The WIFI.OS brand skin — without it the docs render in Starlight's stock theme and read
      // as a different product from the console and marketing site.
      customCss: ['./src/styles/brand.css'],
      sidebar: [
        {
          label: 'Start here',
          items: [
            { label: 'What is WIFI.OS?', slug: 'index' },
            { label: 'Getting started', slug: 'getting-started' },
            { label: 'The dashboard', slug: 'dashboard' },
          ],
        },
        {
          label: 'Selling internet',
          items: [
            { label: 'Hotspot billing', slug: 'hotspot' },
            { label: 'PPPoE (broadband lines)', slug: 'pppoe' },
            { label: 'Plans', slug: 'plans' },
            { label: 'Vouchers', slug: 'vouchers' },
          ],
        },
        {
          label: 'Customers & sales',
          items: [
            { label: 'Clients', slug: 'clients' },
            { label: 'Leads', slug: 'leads' },
            { label: 'Active users', slug: 'active-users' },
            { label: 'Tickets & field jobs', slug: 'field-ops' },
            { label: 'Churn & retention', slug: 'churn' },
          ],
        },
        {
          label: 'Network & field',
          items: [
            { label: 'The map', slug: 'map' },
            { label: 'Network (towers & sectors)', slug: 'network' },
            { label: 'Fibre plant & routing', slug: 'fibre-plant' },
            { label: 'Routers & equipment', slug: 'devices' },
            { label: 'Technician fleet & dispatch', slug: 'fleet' },
          ],
        },
        {
          label: 'Money',
          items: [
            { label: 'Billing & payments', slug: 'billing-payments' },
            { label: 'Wallet & payouts', slug: 'wallet' },
            { label: 'Expenses', slug: 'expenses' },
            { label: 'Reports', slug: 'reports' },
          ],
        },
        {
          label: 'Reaching customers',
          items: [
            { label: 'Communication', slug: 'communication' },
          ],
        },
        {
          label: 'Administration',
          items: [
            { label: 'Your team', slug: 'team' },
            { label: 'Roles & access', slug: 'roles' },
            { label: 'Security & sign-in', slug: 'security' },
            { label: 'Settings', slug: 'settings' },
            { label: 'Developer & API', slug: 'developer-api' },
            { label: 'Install as an app', slug: 'install-app' },
          ],
        },
      ],
    }),
  ],
});
