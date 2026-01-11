/**
 * App Configuration
 * Environment variables for Vultr Object Storage and API endpoints
 */

// These will be replaced at build time by Metro bundler
// For Expo, use process.env.EXPO_PUBLIC_* variables
const Config = {
  vultr: {
    endpoint: process.env.EXPO_PUBLIC_VULTR_ENDPOINT || '',
    bucket: process.env.EXPO_PUBLIC_VULTR_BUCKET || '',
    accessKey: process.env.EXPO_PUBLIC_VULTR_ACCESS_KEY || '',
    secretKey: process.env.EXPO_PUBLIC_VULTR_SECRET_KEY || '',
  },
};

export default Config;
