import { useBottomTabBarHeight } from "@react-navigation/bottom-tabs";

import { useEffect, useRef, useState } from "react";
import {
  Dimensions,
  FlatList,
  ListRenderItemInfo,
  Platform,
  TextStyle,
  View,
  ViewStyle,
  Text,
  Pressable,
  StyleSheet,
  Share,
  ActivityIndicator,
} from "react-native";

import { VideoView, useVideoPlayer } from "expo-video";
import { ReelOverlay } from "../../components/ReelOverlay";
import { Ionicons } from "@expo/vector-icons";
import Config from "../../config";

const { height, width } = Dimensions.get("window");

// Helper function to normalize URLs (remove trailing slashes)
const normalizeUrl = (url: string): string => {
  return url.replace(/\/+$/, ''); // Remove trailing slashes
};

// Configuration pulled from environment variables
const API_BASE_URL = normalizeUrl(process.env.EXPO_PUBLIC_API_BASE_URL || 'http://localhost:8000');
// Video service URL - defaults to same host as backend but port 8002
const getVideoServiceUrl = () => {
  const baseUrl = normalizeUrl(process.env.EXPO_PUBLIC_API_BASE_URL || 'http://localhost:8000');
  if (process.env.EXPO_PUBLIC_VIDEO_SERVICE_URL) {
    return normalizeUrl(process.env.EXPO_PUBLIC_VIDEO_SERVICE_URL);
  }
  // Extract host from base URL and change port to 8002
  try {
    const url = new URL(baseUrl);
    return `${url.protocol}//${url.hostname}:8002`;
  } catch {
    return 'http://localhost:8002';
  }
};
const VIDEO_SERVICE_URL = getVideoServiceUrl();

// Log configuration on startup
console.log('🔧 API Configuration:');
console.log('  API_BASE_URL:', API_BASE_URL);
console.log('  VIDEO_SERVICE_URL:', VIDEO_SERVICE_URL);
console.log('  EXPO_PUBLIC_API_BASE_URL:', process.env.EXPO_PUBLIC_API_BASE_URL || '(not set, using default)');

// Hardcoded sample user ID for testing
const SAMPLE_USER_ID = 'sample-user-123';

// Function to fetch videos using semantic search
async function fetchVideosFromSemanticSearch(resetIfEmpty: boolean = false): Promise<string[]> {
  try {
    // Step 1: Use semantic search to get greenhouse_ids (which are the same as video_ids)
    const searchUrl = `${API_BASE_URL}/jobs/search`;
    console.log("🌐 Starting API request:");
    console.log("  URL:", searchUrl);
    console.log("  Method: POST");
    console.log("  Timestamp:", new Date().toISOString());
    
    const startTime = Date.now();
    let searchResponse: Response;
    
    try {
      searchResponse = await fetch(searchUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify({
          text_prompt: 'software engineer', // Generic search query for feed
          user_id: SAMPLE_USER_ID,
        }),
      });
      
      const elapsed = Date.now() - startTime;
      console.log(`✅ Request completed in ${elapsed}ms`);
      console.log("  Status:", searchResponse.status, searchResponse.statusText);
      console.log("  OK:", searchResponse.ok);
      console.log("  URL resolved to:", searchResponse.url);
      
      // Check if URL changed (redirect)
      if (searchResponse.url !== searchUrl) {
        console.log("  ⚠️  URL was redirected from:", searchUrl, "to:", searchResponse.url);
      }
      
    } catch (fetchError: any) {
      const elapsed = Date.now() - startTime;
      console.error(`❌ Network error after ${elapsed}ms:`);
      console.error("  Error type:", fetchError?.name || 'Unknown');
      console.error("  Error message:", fetchError?.message || String(fetchError));
      console.error("  This usually means:");
      console.error("    - Backend is not running");
      console.error("    - Network connectivity issue");
      console.error("    - URL is incorrect");
      throw fetchError;
    }
    
    if (!searchResponse.ok) {
      console.error(`❌ HTTP error ${searchResponse.status}:`);
      console.error("  Status:", searchResponse.status, searchResponse.statusText);
      console.error("  URL:", searchUrl);
      
      // Try to get error details
      try {
        const errorText = await searchResponse.text();
        console.error("  Response body:", errorText.substring(0, 200));
      } catch (e) {
        console.error("  Could not read error response body");
      }
      
      return [];
    }
    
    const searchData = await searchResponse.json();
    // Extract greenhouse_ids from response (these are the video_ids)
    let videoIds: string[] = searchData.greenhouse_ids || [];
    
    // If no results and resetIfEmpty is true, reset user views and retry
    if (videoIds.length === 0 && resetIfEmpty) {
      console.log("No job IDs found, resetting user views and retrying...");
      
      // Reset user views
      const resetUrl = `${API_BASE_URL}/jobs/reset-user-views?user_id=${SAMPLE_USER_ID}`;
      const resetResponse = await fetch(resetUrl, {
        method: 'GET',
        headers: {
          'Accept': 'application/json',
        },
      });
      
      if (resetResponse.ok) {
        const resetData = await resetResponse.json();
        console.log(`Reset user views: ${resetData.deleted_count} records deleted`);
        
        // Retry semantic search after reset
        const retryResponse = await fetch(searchUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
          },
          body: JSON.stringify({
            text_prompt: 'software engineer',
            user_id: SAMPLE_USER_ID,
          }),
        });
        
        if (retryResponse.ok) {
          const retryData = await retryResponse.json();
          videoIds = retryData.greenhouse_ids || [];
          console.log(`After reset, found ${videoIds.length} video IDs`);
        }
      }
    }
    
    if (videoIds.length === 0) {
      console.log("No job IDs found from search");
      return [];
    }
    
    console.log(`Found ${videoIds.length} video IDs (greenhouse_ids), fetching HLS URLs...`);
    
    // Step 2: For each video_id (greenhouse_id), call video service to get HLS playback URL
    console.log(`📹 Video Service URL: ${VIDEO_SERVICE_URL}`);
    console.log(`📹 Fetching HLS URLs for ${videoIds.length} videos...`);
    
    const videoUrls = await Promise.all(
      videoIds.map(async (videoId: string) => {
        const videoUrl = `${VIDEO_SERVICE_URL}/video/${videoId}`;
        console.log(`  🔍 Fetching HLS URL for video ${videoId}`);
        console.log(`     URL: ${videoUrl}`);
        
        const startTime = Date.now();
        try {
          const videoResponse = await fetch(videoUrl, {
            method: 'GET',
            headers: {
              'Accept': 'application/json',
            },
          });
          
          const elapsed = Date.now() - startTime;
          console.log(`     ✅ Response received in ${elapsed}ms`);
          console.log(`     Status: ${videoResponse.status} ${videoResponse.statusText}`);
          
          if (!videoResponse.ok) {
            console.error(`     ❌ HTTP error ${videoResponse.status} for video ${videoId}`);
            // Try to get error details
            try {
              const errorText = await videoResponse.text();
              console.error(`     Error body: ${errorText.substring(0, 200)}`);
            } catch (e) {
              console.error(`     Could not read error response`);
            }
            return null;
          }
          
          const videoData = await videoResponse.json();
          console.log(`     Response data:`, JSON.stringify(videoData).substring(0, 150));
          
          // Extract playback.url from response
          const playbackUrl = videoData.playback?.url || videoData.url;
          
          if (!playbackUrl) {
            console.warn(`     ⚠️  No playback URL found for video ${videoId}`);
            console.warn(`     Available keys:`, Object.keys(videoData));
            return null;
          }
          
          console.log(`     ✅ Got playback URL: ${playbackUrl}`);
          return playbackUrl;
        } catch (error: any) {
          const elapsed = Date.now() - startTime;
          console.error(`     ❌ Error after ${elapsed}ms for video ${videoId}:`);
          console.error(`     Error type: ${error?.name || 'Unknown'}`);
          console.error(`     Error message: ${error?.message || String(error)}`);
          console.error(`     URL attempted: ${videoUrl}`);
          console.error(`     This usually means:`);
          console.error(`       - Video service is not running on ${VIDEO_SERVICE_URL}`);
          console.error(`       - Video service endpoint /video/${videoId} doesn't exist`);
          console.error(`       - Network/firewall blocking access to port 8002`);
          return null;
        }
      })
    );
    
    // Filter out null values (failed fetches)
    const validUrls = videoUrls.filter((url): url is string => url !== null);
    
    console.log(`Loaded ${validUrls.length} HLS URLs`);
    return validUrls;
  } catch (error: any) {
    console.error("❌ Fatal error in fetchVideosFromSemanticSearch:");
    console.error("  Error type:", error?.name || 'Unknown');
    console.error("  Error message:", error?.message || String(error));
    console.error("  Stack:", error?.stack || 'No stack trace');
    console.error("  This suggests a network/connectivity issue with the backend");
    return [];
  }
}

interface VideoWrapper {
  data: ListRenderItemInfo<string>;
  allVideos: string[];
  visibleIndex: number;
  pause: () => void;
  share: (videoURL: string) => void;
  pauseOverride: boolean;
}

const VideoWrapper = ({
  data,
  allVideos,
  visibleIndex,
  pause,
  pauseOverride,
  share,
}: VideoWrapper) => {
  const bottomHeight = useBottomTabBarHeight();
  const { index, item } = data;

  const player = useVideoPlayer(allVideos[index], (player) => {
    player.loop = true;
    player.muted = false;
  });

  // State for like/dislike
  const [isLiked, setIsLiked] = useState(false);
  const [isDisliked, setIsDisliked] = useState(false);
  const [likeCount, setLikeCount] = useState(12400);
  const [dislikeCount, setDislikeCount] = useState(150);

  const handleLike = () => {
    if (isLiked) {
      setIsLiked(false);
      setLikeCount(likeCount - 1);
    } else {
      setIsLiked(true);
      setLikeCount(likeCount + 1);
      if (isDisliked) {
        setIsDisliked(false);
        setDislikeCount(dislikeCount - 1);
      }
    }
  };

  const handleDislike = () => {
    if (isDisliked) {
      setIsDisliked(false);
      setDislikeCount(dislikeCount - 1);
    } else {
      setIsDisliked(true);
      setDislikeCount(dislikeCount + 1);
      if (isLiked) {
        setIsLiked(false);
        setLikeCount(likeCount - 1);
      }
    }
  };

  // Control playback based on visibility and pause override
  useEffect(() => {
    if (visibleIndex === index && !pauseOverride) {
      player.play();
    } else {
      player.pause();
    }
  }, [visibleIndex, index, pauseOverride, player]);

  // Reset video to 0:00 when scrolling away from it
  useEffect(() => {
    if (visibleIndex !== index) {
      player.currentTime = 0;
    }
  }, [visibleIndex, index, player]);

  return (
    <View
      style={{
        height: Platform.OS === "android" ? height - bottomHeight : height,
        width,
      }}
    >
      <VideoView
        player={player}
        style={{ height: height - bottomHeight, width }}
        contentFit="cover"
        nativeControls={false}
      />

      <Pressable onPress={pause} style={$tapOverlay} />

      <ReelOverlay
        companyName="Company Name"
        title="Video Title Goes Here"
        description="This is a sample description for the video content. It can be up to two lines long."
        likeCount={likeCount}
        dislikeCount={dislikeCount}
        shareCount={3200}
        isLiked={isLiked}
        isDisliked={isDisliked}
        onLike={handleLike}
        onDislike={handleDislike}
        onShare={() => share(item)}
        onProfilePress={() => console.log("Profile pressed")}
      />

      {/* Pause indicator that sticks to this video */}
      {pauseOverride && visibleIndex === index && (
        <View style={$pauseIndicator}>
          <Ionicons name="pause" size={60} color="#fff" style={{ opacity: 0.3 }} />
        </View>
      )}
    </View>
  );
};

export default function HomeScreen() {
  const bottomHeight = useBottomTabBarHeight();

  const [allVideos, setAllVideos] = useState<string[]>([]);
  const [visibleIndex, setVisibleIndex] = useState(0);
  const [pauseOverride, setPauseOverride] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const numOfRefreshes = useRef(0);
  const hasMore = useRef(true);
  const prefetchedManifests = useRef<Set<string>>(new Set());

  // Prefetch manifests for next 2 videos when visible index changes
  useEffect(() => {
    const prefetchManifests = async () => {
      const nextIndices = [visibleIndex + 1, visibleIndex + 2];
      for (const idx of nextIndices) {
        if (idx < allVideos.length && allVideos[idx]) {
          const manifestUrl = allVideos[idx];
          if (!prefetchedManifests.current.has(manifestUrl)) {
            try {
              await fetch(manifestUrl);
              prefetchedManifests.current.add(manifestUrl);
              console.log(`Prefetched manifest for video ${idx}`);
            } catch (error) {
              console.warn(`Failed to prefetch manifest ${manifestUrl}:`, error);
            }
          }
        }
      }
    };
    
    if (allVideos.length > 0) {
      prefetchManifests();
    }
  }, [visibleIndex, allVideos]);

  // Load initial videos from backend
  useEffect(() => {
    async function loadInitialVideos() {
      try {
        setLoading(true);
        const videos = await fetchVideosFromSemanticSearch(false);
        
        if (videos.length === 0) {
          setError("No videos found");
        } else {
          setAllVideos(videos);
        }
      } catch (err) {
        console.error("Error loading videos:", err);
        setError("Failed to load videos");
      } finally {
        setLoading(false);
      }
    }

    loadInitialVideos();
  }, []);

  const fetchMoreData = async () => {
    // Fetch more videos using semantic search
    // If search returns 0 results, reset user views and retry
    try {
      const moreVideos = await fetchVideosFromSemanticSearch(true);
      
      if (moreVideos.length > 0) {
        setAllVideos((prevVideos) => [...prevVideos, ...moreVideos]);
        console.log(`Added ${moreVideos.length} more videos. Total: ${allVideos.length + moreVideos.length}`);
      } else {
        console.log("No more videos available even after reset");
      }
    } catch (err) {
      console.error("Error fetching more videos:", err);
    }
  };

  const onViewableItemsChanged = (event: any) => {
    const newIndex = Number(event.viewableItems.at(-1).key);
    setVisibleIndex(newIndex);
  };

  const pause = () => {
    setPauseOverride(!pauseOverride);
  };

  const share = (videoURL: string) => {
    setPauseOverride(true);
    setTimeout(() => {
      Share.share({
        title: "Share This Video",
        message: `Check out: ${videoURL}`,
      });
    }, 100);
  };

  // Show loading state
  if (loading) {
    return (
      <View style={{ flex: 1, backgroundColor: "black", justifyContent: "center", alignItems: "center" }}>
        <ActivityIndicator size="large" color="#fff" />
        <Text style={{ color: "#fff", marginTop: 20 }}>Loading videos...</Text>
      </View>
    );
  }

  // Show error state
  if (error || allVideos.length === 0) {
    return (
      <View style={{ flex: 1, backgroundColor: "black", justifyContent: "center", alignItems: "center", padding: 20 }}>
        <Ionicons name="cloud-offline" size={60} color="#fff" style={{ opacity: 0.5 }} />
        <Text style={{ color: "#fff", marginTop: 20, fontSize: 18, textAlign: "center" }}>
          {error || "No videos available"}
        </Text>
        <Text style={{ color: "#aaa", marginTop: 10, fontSize: 14, textAlign: "center" }}>
          Make sure your backend is running and Vultr Object Storage is configured
        </Text>
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: "black" }}>
      <FlatList
        pagingEnabled
        snapToInterval={
          Platform.OS === "android" ? height - bottomHeight : undefined
        }
        initialNumToRender={1}
        showsVerticalScrollIndicator={false}
        onViewableItemsChanged={onViewableItemsChanged}
        data={allVideos}
        onEndReachedThreshold={0.3}
        onEndReached={fetchMoreData}
        renderItem={(data) => {
          return (
            <VideoWrapper
              data={data}
              allVideos={allVideos}
              visibleIndex={visibleIndex}
              pause={pause}
              share={share}
              pauseOverride={pauseOverride}
            />
          );
        }}
      />
    </View>
  );
}

const $tapOverlay: ViewStyle = {
  ...StyleSheet.absoluteFillObject,
  backgroundColor: "transparent",
};

const $pauseIndicator: ViewStyle = {
  position: "absolute",
  top: "50%",
  left: "50%",
  transform: [{ translateX: -30 }, { translateY: -30 }],
  justifyContent: "center",
  alignItems: "center",
  pointerEvents: "none",
};



