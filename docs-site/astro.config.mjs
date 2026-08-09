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
          label: 'Running the business',
          items: [
            { label: 'Clients', slug: 'clients' },
            { label: 'Billing & payments', slug: 'billing-payments' },
            { label: 'Active users', slug: 'active-users' },
            { label: 'Churn & retention', slug: 'churn' },
          ],
        },
        {
          label: 'Administration',
          items: [
            { label: 'Settings', slug: 'settings' },
            { label: 'Roles & access', slug: 'roles' },
          ],
        },
      ],
    }),
  ],
});
