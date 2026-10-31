'use strict';
const {defineConfig}=require('@playwright/test');
const url=process.env.SENTINEL_JOURNEY_BASE_URL;
if (!url) throw new Error('SENTINEL_JOURNEY_BASE_URL is required for opt-in journey capture');
module.exports=defineConfig({testDir:'.',testMatch:'dashboard-journey.spec.js',timeout:120000,
  expect:{timeout:5000},workers:1,retries:0,fullyParallel:false,forbidOnly:true,reporter:'json',
  use:{baseURL:url,serviceWorkers:'allow',viewport:{width:393,height:852},screenshot:'off',trace:'off',video:'off'},
  projects:[{name:'webkit-iphone',use:{browserName:'webkit'}},
    {name:'chromium-pwa',use:{browserName:'chromium',channel:process.env.SENTINEL_BROWSER_CHANNEL || 'chromium'}}]});
