// app/(tabs)/index.tsx

import { useBottomTabBarHeight } from "@react-navigation/bottom-tabs";
import { useEffect, useRef, useState } from "react";
import {
  Dimensions,
  FlatList,
  ListRenderItemInfo,
  Platform,
  View,
  Text,
  Pressable,
  StyleSheet,
  Share,
  ActivityIndicator,
  ViewStyle,
} from "react-native";

import { VideoView, useVideoPlayer } from "expo-video";
import type { VideoPlayerStatus } from "expo-video";
import { Audio } from "expo-av";
import { ReelOverlay } from "../../components/ReelOverlay";
import { OTPInputModal } from "../../components/OTPInputModal";
import { Ionicons } from "@expo/vector-icons";
import Config from "../../config";
import { useAuth } from "@/contexts/AuthContext";
import { useApplied } from "@/contexts/AppliedContext";

const { height, width } = Dimensions.get("window");

// ✅ Kill-switch: set EXPO_PUBLIC_DISABLE_FEED=true to stop ALL video/network logic
const DISABLE_FEED = process.env.EXPO_PUBLIC_DISABLE_FEED === "true";
console.log("🚦 FEED STATUS:", DISABLE_FEED ? "DISABLED (AUTH MODE)" : "ENABLED");

// Helper function to normalize URLs (remove trailing slashes)
const normalizeUrl = (url: string): string => {
  return url.replace(/\/+$/, "");
};

// Configuration pulled from environment variables
const API_BASE_URL = normalizeUrl(
  process.env.EXPO_PUBLIC_API_BASE_URL || "http://localhost:8000"
);

// Video service URL - defaults to same host as backend but port 8002
const getVideoServiceUrl = () => {
  const baseUrl = normalizeUrl(
    process.env.EXPO_PUBLIC_API_BASE_URL || "http://localhost:8000"
  );

  if (process.env.EXPO_PUBLIC_VIDEO_SERVICE_URL) {
    return normalizeUrl(process.env.EXPO_PUBLIC_VIDEO_SERVICE_URL);
  }

  // Extract host from base URL and change port to 8002
  try {
    const url = new URL(baseUrl);
    return `${url.protocol}//${url.hostname}:8002`;
  } catch {
    return "http://localhost:8002";
  }
};
const VIDEO_SERVICE_URL = getVideoServiceUrl();

// Headless service URL - defaults to same host as backend but port 8001
const getHeadlessServiceUrl = () => {
  const baseUrl = normalizeUrl(
    process.env.EXPO_PUBLIC_API_BASE_URL || "http://localhost:8000"
  );

  if (process.env.EXPO_PUBLIC_HEADLESS_SERVICE_URL) {
    return normalizeUrl(process.env.EXPO_PUBLIC_HEADLESS_SERVICE_URL);
  }

  // Extract host from base URL and change port to 8001
  try {
    const url = new URL(baseUrl);
    return `${url.protocol}//${url.hostname}:8001`;
  } catch {
    return "http://localhost:8001";
  }
};
const HEADLESS_SERVICE_URL = getHeadlessServiceUrl();

// Log configuration on startup
console.log("🔧 API Configuration:");
console.log("  API_BASE_URL:", API_BASE_URL);
console.log("  VIDEO_SERVICE_URL:", VIDEO_SERVICE_URL);
console.log("  HEADLESS_SERVICE_URL:", HEADLESS_SERVICE_URL);
console.log(
  "  EXPO_PUBLIC_API_BASE_URL:",
  process.env.EXPO_PUBLIC_API_BASE_URL || "(not set, using default)"
);
console.log(
  "  EXPO_PUBLIC_HEADLESS_SERVICE_URL:",
  process.env.EXPO_PUBLIC_HEADLESS_SERVICE_URL || "(not set, will derive from API_BASE_URL)"
);

// Video data structure
interface VideoData {
  videoUrl: string;
  greenhouseId: string;
  companyName?: string;
  title?: string;
  description?: string;
}

// Function to fetch videos using semantic search
async function fetchVideosFromSemanticSearch(
  user_id: string,
  text_prompt: string,
  resetIfEmpty: boolean = false
): Promise<VideoData[]> {
  // ✅ Hard guard: if feed disabled, return immediately with no network calls
  if (DISABLE_FEED) return [];

  try {
    // Step 1: Call search jobs endpoint to get greenhouse_ids
    console.log("🔍 Calling /jobs/search endpoint...");
    const searchUrl = `${API_BASE_URL}/jobs/search`;
    console.log(`  URL: ${searchUrl}`);
    console.log(`  user_id: ${user_id}`);
    console.log(`  text_prompt: ${text_prompt}`);

    const searchResponse = await fetch(searchUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        user_id,
        text_prompt,
      }),
    });

    if (!searchResponse.ok) {
      console.error(`❌ Search jobs failed: ${searchResponse.status} ${searchResponse.statusText}`);
      try {
        const errorText = await searchResponse.text();
        console.error(`Error body: ${errorText.substring(0, 200)}`);
      } catch (e) {
        console.error("Could not read error response");
      }
      return [];
    }

    const searchData = await searchResponse.json();
    const videoIds: string[] = searchData.greenhouse_ids || [];
    console.log(`✅ Found ${videoIds.length} video IDs (greenhouse_ids), fetching HLS URLs...`);
    console.log(`📋 VIDEO IDS FROM BACKEND:`, JSON.stringify(videoIds));

    if (videoIds.length === 0) {
      console.log("No videos found from search");
      return [];
    }

    // Step 2: For each video_id (greenhouse_id), call video service to get HLS playback URL
    console.log(`📹 Video Service URL: ${VIDEO_SERVICE_URL}`);
    console.log(`📹 Fetching HLS URLs for ${videoIds.length} videos...`);

    const videoDataArray = await Promise.all(
      videoIds.map(async (videoId: string) => {
        const videoUrl = `${VIDEO_SERVICE_URL}/video/${videoId}`;
        console.log(`  🔍 Fetching HLS URL for video ${videoId}`);

        const startTime = Date.now();
        try {
          const videoResponse = await fetch(videoUrl, {
            method: "GET",
            headers: {
              Accept: "application/json",
            },
          });

          const elapsed = Date.now() - startTime;
          console.log(`     ✅ Response received in ${elapsed}ms`);

          if (!videoResponse.ok) {
            console.error(
              `     ❌ HTTP error ${videoResponse.status} for video ${videoId}`
            );
            return null;
          }

          const videoData = await videoResponse.json();
          // Extract playback.url from response
          const playbackUrl = videoData.playback?.url || videoData.url;

          if (!playbackUrl) {
            console.warn(
              `     ⚠️  No playback URL found for video ${videoId}`
            );
            return null;
          }

          console.log(`     ✅ Got playback URL for ${videoId}: ${playbackUrl}`);
          return {
            videoUrl: playbackUrl,
            greenhouseId: videoId,
            companyName: videoData.company_name,
            title: videoData.title,
            description: videoData.description,
          };
        } catch (error: any) {
          const elapsed = Date.now() - startTime;
          console.error(
            `     ❌ Error after ${elapsed}ms for video ${videoId}: ${error?.message || String(error)}`
          );
          return null;
        }
      })
    );

    // Filter out null values (failed fetches)
    const validVideos = videoDataArray.filter((video) => video !== null) as VideoData[];

    console.log(`✅ Loaded ${validVideos.length} HLS URLs`);
    console.log(`📺 FINAL VIDEO LIST:`);
    validVideos.forEach((v, i) => {
      console.log(`   [${i}] greenhouseId=${v.greenhouseId}, url=${v.videoUrl}`);
    });
    return validVideos;
  } catch (error: any) {
    console.error("❌ Fatal error in fetchVideosFromSemanticSearch:");
    console.error("  Error type:", error?.name || "Unknown");
    console.error("  Error message:", error?.message || String(error));
    console.error("  Stack:", error?.stack || "No stack trace");
    return [];
  }
}

interface VideoWrapperProps {
  data: ListRenderItemInfo<VideoData>;
  allVideos: VideoData[];
  visibleIndex: number;
  pause: () => void;
  share: (videoURL: string) => void;
  pauseOverride: boolean;
  user: { user_id: string } | null;
  setPendingApplicationId: (id: string | null) => void;
  setShowOTPModal: (show: boolean) => void;
}

const VideoWrapper = ({
  data,
  allVideos,
  visibleIndex,
  pause,
  pauseOverride,
  share,
  user,
  setPendingApplicationId,
  setShowOTPModal,
}: VideoWrapperProps) => {
  const bottomHeight = useBottomTabBarHeight();
  const { index, item } = data;
  const { incrementApplied } = useApplied();

  // Track if this video should be playing
  const shouldPlay = visibleIndex === index && !pauseOverride;
  const [playerStatus, setPlayerStatus] = useState<VideoPlayerStatus>("idle");

  // Always create player with real URL - the player handles lazy loading internally
  const videoUrl = allVideos[index].videoUrl;
  console.log(`🎬 [Video ${index}] Creating player with URL: ${videoUrl}`);
  const player = useVideoPlayer(videoUrl, (player) => {
    player.loop = true;
    player.muted = false;
  });
  useEffect(() => {
    const subscription = player.addListener("statusChange", (payload) => {
      setPlayerStatus(payload.status);
      if (payload.status === "error") {
        console.warn(`[Video ${index}] Player error:`, payload.error);
      } else {
        console.log(`[Video ${index}] Player status: ${payload.status}`);
      }
    });

    return () => {
      subscription.remove();
    };
  }, [player, index]);

  // Generate random like/dislike counts on mount (different for each video)
  const [isLiked, setIsLiked] = useState(false);
  const [isDisliked, setIsDisliked] = useState(false);
  // Generate random counts: likes between 1K-50K, dislikes between 50-500
  const [likeCount, setLikeCount] = useState(() => {
    const base = 1000 + Math.floor(Math.random() * 49000);
    return base;
  });
  const [dislikeCount, setDislikeCount] = useState(() => {
    const base = 50 + Math.floor(Math.random() * 450);
    return base;
  });

  const handleLike = () => {
    // Lock the upvote button - once liked, cannot be removed
    if (isLiked) {
      return; // Already liked, do nothing
    }
    
    setIsLiked(true);
    setLikeCount(likeCount + 1);
    if (isDisliked) {
      setIsDisliked(false);
      setDislikeCount(dislikeCount - 1);
    }

    // Increment applied count when user upvotes a reel
    incrementApplied();

    // Call submit_application when user upvotes (fire-and-forget - don't await)
    // This is a long-running operation that can take several minutes, so we
    // submit it in the background without blocking the UI
    if (user?.user_id) {
      const greenhouseId = allVideos[index].greenhouseId;
      const submitUrl = `${HEADLESS_SERVICE_URL}/api/v1/applications/analyze`;
      console.log(`📝 Submitting application for job ${greenhouseId} (background)...`);
      console.log(`🔗 Target URL: ${submitUrl}`);
      console.log(`🔗 HEADLESS_SERVICE_URL: ${HEADLESS_SERVICE_URL}`);
      
      // Fire-and-forget: don't await this long-running operation
      fetch(submitUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-User-ID": user.user_id,
        },
        body: JSON.stringify({
          job_id: greenhouseId,
          auto_submit: true,
        }),
      })
        .then(async (response) => {
          if (!response.ok) {
            const errorText = await response.text();
            console.error(`❌ Failed to submit application: ${response.status} ${response.statusText}`, errorText);
          } else {
            const result = await response.json();
            console.log(`✅ Application response:`, result);

            // Check if 2FA verification is required
            if (result.status === "pending_verification") {
              console.log(`🔐 2FA required for application ${result.application_id}`);
              setPendingApplicationId(result.application_id);
              setShowOTPModal(true);
            } else if (result.status === "submitted") {
              console.log(`✅ Application submitted successfully!`);
            } else if (result.status === "failed") {
              const errorMessage = result.error || result.message || "";
              console.error(`❌ Application failed: ${errorMessage}`);
              
              // Check if email verification is required
              if (errorMessage.toLowerCase().includes("email verification") || 
                  errorMessage.toLowerCase().includes("verification required")) {
                console.log(`🔐 Email verification required for application ${result.application_id}`);
                if (result.application_id) {
                  setPendingApplicationId(result.application_id);
                  setShowOTPModal(true);
                } else {
                  console.error(`❌ Application ID missing in failed response`);
                }
              }
            }
          }
        })
        .catch((error: any) => {
          // Timeout errors are expected for long-running operations
          // The application is still being processed on the server
          console.error(`❌ Error submitting application:`, error?.message || String(error));
          console.error(`❌ Error details - URL was: ${submitUrl}`);
          console.error(`❌ Error details - HEADLESS_SERVICE_URL: ${HEADLESS_SERVICE_URL}`);
        });
    }
  };

  const handleDislike = () => {
    // Cannot dislike if already liked (upvote is locked)
    if (isLiked) {
      return; // Cannot remove like once upvoted
    }
    
    if (isDisliked) {
      setIsDisliked(false);
      setDislikeCount(dislikeCount - 1);
    } else {
      setIsDisliked(true);
      setDislikeCount(dislikeCount + 1);
    }
  };

  // Simple playback control - just play/pause based on visibility
  useEffect(() => {
    console.log(`[Video ${index}] Effect running: shouldPlay=${shouldPlay}, visibleIndex=${visibleIndex}, pauseOverride=${pauseOverride}`);
    
    if (shouldPlay) {
      if (playerStatus !== "readyToPlay") {
        console.log(
          `[Video ${index}] Waiting for readyToPlay (status=${playerStatus})`
        );
        return;
      }
      console.log(`[Video ${index}] Calling player.play()`);
      try {
        player.play();
      } catch (error) {
        console.warn(`[Video ${index}] Play error:`, error);
      }
    } else {
      console.log(`[Video ${index}] Calling player.pause()`);
      try {
        player.pause();
      } catch (e) {
        console.warn(`[Video ${index}] Pause error:`, e);
      }
    }
  }, [shouldPlay, visibleIndex, pauseOverride, index]);

  // Reset video to 0:00 when scrolling away from it
  useEffect(() => {
    if (visibleIndex !== index) {
      try {
        player.currentTime = 0;
      } catch (e) {
        // Ignore reset errors
      }
    }
  }, [visibleIndex, index]);

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
        companyName={allVideos[index].companyName || "Company"}
        title={allVideos[index].title || "Job Title"}
        description={allVideos[index].description || "Job description"}
        likeCount={likeCount}
        dislikeCount={dislikeCount}
        shareCount={3200}
        isLiked={isLiked}
        isDisliked={isDisliked}
        onLike={handleLike}
        onDislike={handleDislike}
        onShare={() => share(item.videoUrl)}
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
  const { user, token } = useAuth();

  const [allVideos, setAllVideos] = useState<VideoData[]>([]);
  const [visibleIndex, setVisibleIndex] = useState(0);
  const [pauseOverride, setPauseOverride] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [userPrompt, setUserPrompt] = useState<string>("software engineering jobs");

  // State for email verification OTP modal
  const [showOTPModal, setShowOTPModal] = useState(false);
  const [otpCode, setOtpCode] = useState<string | null>(null);
  const [pendingApplicationId, setPendingApplicationId] = useState<string | null>(null);

  // Expose function to trigger OTP modal from console (for testing)
  useEffect(() => {
    const triggerOTP = () => {
      console.log('🔔 Triggering OTP modal for testing...');
      setShowOTPModal(true);
    };
    
    // Expose to both global (React Native) and window (web debugger)
    if (typeof global !== 'undefined') {
      // @ts-ignore - Exposing test function globally
      global.__testTriggerOTP = triggerOTP;
    }
    if (typeof window !== 'undefined') {
      // @ts-ignore - Exposing test function for web debugger
      window.__testTriggerOTP = triggerOTP;
    }
    
    console.log('💡 Test function available: Run __testTriggerOTP() in console to test OTP modal');
    
    return () => {
      if (typeof global !== 'undefined') {
        // @ts-ignore
        delete global.__testTriggerOTP;
      }
      if (typeof window !== 'undefined') {
        // @ts-ignore
        delete window.__testTriggerOTP;
      }
    };
  }, []);

  const prefetchedManifests = useRef<Set<string>>(new Set());

  // ✅ If feed is disabled, NEVER prefetch anything
  useEffect(() => {
    if (DISABLE_FEED) return;

    const prefetchManifests = async () => {
      const nextIndices = [visibleIndex + 1, visibleIndex + 2];
      for (const idx of nextIndices) {
        if (idx < allVideos.length && allVideos[idx]) {
          const manifestUrl = allVideos[idx].videoUrl;
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

  // Configure audio mode for video playback
  useEffect(() => {
    if (DISABLE_FEED) return;

    async function configureAudio() {
      try {
        await Audio.setAudioModeAsync({
          playsInSilentModeIOS: true,
          allowsRecordingIOS: false,
          interruptionModeIOS: 1, // 1 = DoNotMix (interrupt other audio)
          staysActiveInBackground: false,
          shouldDuckAndroid: true,
        });
      } catch (error) {
        console.warn("Failed to configure audio mode:", error);
      }
    }
    configureAudio();
  }, []);

  // Fetch user's prompt from backend
  useEffect(() => {
    async function fetchUserPrompt() {
      if (!token || !user) return;

      try {
        const response = await fetch(`${API_BASE_URL}/auth/me`, {
          method: "GET",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
        });

        if (response.ok) {
          const userData = await response.json();
          if (userData.prompt) {
            setUserPrompt(userData.prompt);
          }
        }
      } catch (err) {
        console.error("Error fetching user prompt:", err);
      }
    }

    fetchUserPrompt();
  }, [token, user]);

  // ✅ Load initial videos from backend (GATED)
  useEffect(() => {
    if (DISABLE_FEED) {
      console.log("🛑 Feed disabled — skipping video startup");
      setLoading(false);
      setAllVideos([]);
      setError(null);
      return;
    }

    if (!user?.user_id) {
      console.log("⏳ Waiting for user authentication...");
      return;
    }

    async function loadInitialVideos() {
      if (!user?.user_id) return;
      
      try {
        setLoading(true);
        const videos = await fetchVideosFromSemanticSearch(
          user.user_id,
          userPrompt,
          false
        );

        if (videos.length === 0) {
          setError("No videos found");
        } else {
          console.log(`🎯 SETTING allVideos with ${videos.length} videos:`);
          videos.forEach((v, i) => {
            console.log(`   [${i}] ${v.greenhouseId} -> ${v.videoUrl}`);
          });
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
  }, [user?.user_id, userPrompt]);

  // Check if queue has 3 or fewer videos and fetch more
  useEffect(() => {
    if (DISABLE_FEED) return;
    if (!user?.user_id) return;
    if (loading) return; // Don't fetch while initial load is happening

    async function checkAndFetchMore() {
      if (allVideos.length <= 3 && user?.user_id) {
        console.log(`📊 Queue has ${allVideos.length} videos (<= 3), fetching more...`);
        try {
          const moreVideos = await fetchVideosFromSemanticSearch(
            user.user_id,
            userPrompt,
            false
          );

          if (moreVideos.length > 0) {
            setAllVideos((prevVideos) => [...prevVideos, ...moreVideos]);
            console.log(
              `✅ Added ${moreVideos.length} more videos. Total: ${
                allVideos.length + moreVideos.length
              }`
            );
          } else {
            console.log("⚠️ No more videos available");
          }
        } catch (err) {
          console.error("Error fetching more videos:", err);
        }
      }
    }

    checkAndFetchMore();
  }, [allVideos.length, user?.user_id, userPrompt, loading]);

  const fetchMoreData = async () => {
    if (DISABLE_FEED) return;
    if (!user?.user_id) return;

    try {
      const moreVideos = await fetchVideosFromSemanticSearch(
        user.user_id,
        userPrompt,
        false
      );

      if (moreVideos.length > 0) {
        setAllVideos((prevVideos) => [...prevVideos, ...moreVideos]);
        console.log(
          `✅ Added ${moreVideos.length} more videos. Total: ${
            allVideos.length + moreVideos.length
          }`
        );
      } else {
        console.log("⚠️ No more videos available");
      }
    } catch (err) {
      console.error("Error fetching more videos:", err);
    }
  };

  const onViewableItemsChanged = (event: any) => {
    const lastItem = event.viewableItems.at(-1);
    if (!lastItem) return;
    
    // Extract index from key (format: "video-{index}" or just the index)
    const key = lastItem.key;
    const newIndex = key?.startsWith?.("video-") 
      ? Number(key.replace("video-", ""))
      : Number(key);
    
    if (!Number.isNaN(newIndex) && newIndex !== visibleIndex) {
      console.log(`[FlatList] Visible index changed: ${visibleIndex} → ${newIndex}`);
      setVisibleIndex(newIndex);
    }
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

  // ✅ AUTH MODE SCREEN (no feed mounts at all)
  if (DISABLE_FEED) {
    return (
      <View
        style={{
          flex: 1,
          backgroundColor: "black",
          justifyContent: "center",
          alignItems: "center",
          paddingHorizontal: 24,
        }}
      >
        <Text style={{ color: "#fff", fontSize: 22, fontWeight: "600" }}>
          Auth Mode
        </Text>
        <Text
          style={{
            color: "#aaa",
            marginTop: 12,
            fontSize: 14,
            textAlign: "center",
            lineHeight: 20,
          }}
        >
          Feed is disabled via EXPO_PUBLIC_DISABLE_FEED=true.
          {"\n"}
          No video services will initialize.
        </Text>
      </View>
    );
  }

  // Show loading state
  if (loading) {
    return (
      <View
        style={{
          flex: 1,
          backgroundColor: "black",
          justifyContent: "center",
          alignItems: "center",
        }}
      >
        <ActivityIndicator size="large" color="#fff" />
        <Text style={{ color: "#fff", marginTop: 20 }}>
          Loading videos...
        </Text>
      </View>
    );
  }

  // Show error state
  if (error || allVideos.length === 0) {
    return (
      <View
        style={{
          flex: 1,
          backgroundColor: "black",
          justifyContent: "center",
          alignItems: "center",
          padding: 20,
        }}
      >
        <Ionicons
          name="cloud-offline"
          size={60}
          color="#fff"
          style={{ opacity: 0.5 }}
        />
        <Text
          style={{
            color: "#fff",
            marginTop: 20,
            fontSize: 18,
            textAlign: "center",
          }}
        >
          {error || "No videos available"}
        </Text>
        <Text
          style={{
            color: "#aaa",
            marginTop: 10,
            fontSize: 14,
            textAlign: "center",
          }}
        >
          Make sure your backend is running and Vultr Object Storage is configured
        </Text>
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: "black" }}>
      <FlatList
        pagingEnabled
        snapToInterval={Platform.OS === "android" ? height - bottomHeight : undefined}
        initialNumToRender={1}
        maxToRenderPerBatch={2}
        windowSize={3}
        removeClippedSubviews={true}
        showsVerticalScrollIndicator={false}
        onViewableItemsChanged={onViewableItemsChanged}
        data={allVideos}
        onEndReachedThreshold={0.3}
        onEndReached={fetchMoreData}
        keyExtractor={(item, index) => `video-${index}`}
        renderItem={(data) => {
          return (
            <VideoWrapper
              data={data}
              allVideos={allVideos}
              visibleIndex={visibleIndex}
              pause={pause}
              share={share}
              pauseOverride={pauseOverride}
              user={user}
              setPendingApplicationId={setPendingApplicationId}
              setShowOTPModal={setShowOTPModal}
            />
          );
        }}
      />

      {/* OTP Input Modal - shows on top of everything when email verification is required */}
      <OTPInputModal
        visible={showOTPModal}
        onCodeSubmit={async (code: string) => {
          console.log("OTP Code submitted:", code);
          setOtpCode(code);

          if (pendingApplicationId && user?.user_id) {
            try {
              const verifyUrl = `${HEADLESS_SERVICE_URL}/api/v1/applications/${pendingApplicationId}/verify`;
              console.log(`🔐 Verifying application ${pendingApplicationId} with code...`);

              const response = await fetch(verifyUrl, {
                method: "POST",
                headers: {
                  "Content-Type": "application/json",
                  "X-User-ID": user.user_id,
                },
                body: JSON.stringify({ code }),
              });

              const result = await response.json();
              console.log(`🔐 Verification result:`, result);

              if (result.status === "submitted") {
                console.log(`✅ Application verified and submitted!`);
              } else {
                console.error(`❌ Verification failed: ${result.error || result.message}`);
              }
            } catch (error) {
              console.error(`❌ Verification request failed:`, error);
            }
          }

          setShowOTPModal(false);
          setPendingApplicationId(null);
        }}
        onCancel={() => {
          setShowOTPModal(false);
          setOtpCode(null);
          setPendingApplicationId(null);
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
