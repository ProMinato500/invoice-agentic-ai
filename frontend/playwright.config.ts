import { defineConfig } from '@playwright/test';
export default defineConfig({testDir:'./tests',timeout:600000,use:{baseURL:'http://127.0.0.1:3000',headless:true,trace:'retain-on-failure'},reporter:'list',workers:1});
